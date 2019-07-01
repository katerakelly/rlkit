"""
Run Prototypical Soft Actor Critic on point mass.

"""
import os
import numpy as np
import click
import datetime
import pathlib

# from rlkit.envs.point_mass import PointEnv
from rlkit.envs.wrappers import NormalizedBoxEnv
from rlkit.launchers.launcher_util import setup_logger
from rlkit.torch.sac.policies import TanhGaussianPolicy
from rlkit.torch.networks import FlattenMlp, MlpEncoder, RecurrentEncoder
from rlkit.torch.sac.sac import ProtoSoftActorCritic
from rlkit.torch.sac.proto import ProtoAgent
import rlkit.torch.pytorch_util as ptu


# from multiworld.envs.mujoco.sawyer_xyz.sawyer_assembly_peg_6dof import SawyerNutAssembly6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_bin_picking_6dof import SawyerBinPicking6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_book_place import SawyerBookPlace6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_box_close_6dof import SawyerBoxClose6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_reach import SawyerReachXYZEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_hand_insert import SawyerHandInsert6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_sweep import SawyerSweep6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_hammer_6dof import SawyerHammer6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_laptop_close_6dof import SawyerLaptopClose6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_sweep_into_goal import SawyerSweepIntoGoal6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_button_press_topdown_6dof import SawyerButtonPressTopdown6DOFEnv
from multiworld.envs.mujoco.sawyer_xyz.sawyer_reach_push_pick_place_6dof import SawyerReachPushPickPlace6DOFEnv
from multiworld.envs.mujoco.sawyer_xyz.sawyer_dial_turn_6dof import SawyerDialTurn6DOFEnv

# from multiworld.envs.mujoco.sawyer_xyz.sawyer_door_6dof import SawyerDoor6DOFEnv
# from multiworld.envs.mujoco.sawyer_xyz.sawyer_drawer_close_6dof import SawyerDrawerClose6DOFEnv

N_TASKS = 50

def datetimestamp(divider=''):
    now = datetime.datetime.now()
    return now.strftime('%Y-%m-%d-%H-%M-%S-%f').replace('-', divider)

def experiment(variant):
    ptu.set_gpu_mode(variant['use_gpu'], variant['gpu_id'])

    goal_low = np.array((0.1 - .5, 0.8 - .5, 0.2))
    goal_high = np.array((0.1 + .5, 0.8 + .5, 0.2))

    goals = np.random.uniform(low=goal_low, high=goal_high, size=(N_TASKS, len(goal_low))).tolist()

    # Initialize copies of each environment with random goals.
    tasks = []
    for i in range(N_TASKS):
        tasks.append(SawyerReachPushPickPlace6DOFEnv(if_render=False, fix_goal=goals[i], fix_task=True, task_idx=2, multitask=False))


    for env in tasks:
        print('env.observation_space.shape', env.observation_space.shape)
        print('env.action_space.shape))', env.action_space.shape)

    obs_dim = int(np.prod(tasks[0].observation_space.shape))
    action_dim = int(np.prod(tasks[0].action_space.shape))
    latent_dim = 7
    task_enc_output_dim = latent_dim * 2 if variant['algo_params']['use_information_bottleneck'] else latent_dim
    reward_dim = 1

    net_size = variant['net_size']
    # start with linear task encoding
    recurrent = variant['algo_params']['recurrent']
    encoder_model = RecurrentEncoder if recurrent else MlpEncoder
    task_enc = encoder_model(
            hidden_sizes=[200, 200, 200], # deeper net + higher dim space generalize better
            input_size=obs_dim + action_dim + reward_dim,
            output_size=task_enc_output_dim,
    )
    qf1 = FlattenMlp(
        hidden_sizes=[net_size, net_size, net_size],
        input_size=obs_dim + action_dim + latent_dim,
        output_size=1,
    )
    qf2 = FlattenMlp(
        hidden_sizes=[net_size, net_size, net_size],
        input_size=obs_dim + action_dim + latent_dim,
        output_size=1,
    )
    vf = FlattenMlp(
        hidden_sizes=[net_size, net_size, net_size],
        input_size=obs_dim + latent_dim,
        output_size=1,
    )
    policy = TanhGaussianPolicy(
        hidden_sizes=[net_size, net_size, net_size],
        obs_dim=obs_dim + latent_dim,
        latent_dim=latent_dim,
        action_dim=action_dim,
    )

    rf = FlattenMlp(
        hidden_sizes=[net_size, net_size, net_size],
        input_size=obs_dim + action_dim + latent_dim,
        output_size=1
    )

    agent = ProtoAgent(
        latent_dim,
        [task_enc, policy, qf1, qf2, vf, rf],
        **variant['algo_params']
    )

    algorithm = ProtoSoftActorCritic(
        envs=tasks,
        train_tasks=list(tasks[:50]),
        eval_tasks=list(tasks[10:]),
        nets=[agent, task_enc, policy, qf1, qf2, vf, rf],
        latent_dim=latent_dim,
        **variant['algo_params']
    )
    if ptu.gpu_enabled():
        algorithm.to()
    algorithm.train()


@click.command()
@click.argument('gpu', default=0)
@click.option('--docker', default=0)
def main(gpu, docker):
    max_path_length = 150
    # noinspection PyTypeChecker
    variant = dict(
        task_params=dict(
            n_tasks=1,
            randomize_tasks=True,
        ),
        algo_params=dict(
            meta_batch=16,
            num_iterations=10000,
            num_tasks_sample=5,
            num_steps_per_task=10 * max_path_length,
            num_train_steps_per_itr=1000,
            num_evals=5, # number of evals with separate task encodings
            num_steps_per_eval=3 * max_path_length,  # num transitions to eval on
            batch_size=256,  # to compute training grads from
            embedding_batch_size=64,
            embedding_mini_batch_size=64,
            max_path_length=max_path_length,
            discount=0.99,
            soft_target_tau=0.005,
            policy_lr=3E-4,
            qf_lr=3E-4,
            vf_lr=3E-4,
            context_lr=3e-4,
            reward_scale=10.,
            sparse_rewards=False,
            reparameterize=True,
            kl_lambda=.1,
            rf_loss_scale=1.,
            use_information_bottleneck=True,
            train_embedding_source='online_exploration_trajectories',
            # embedding_source should be chosen from
            # {'initial_pool', 'online_exploration_trajectories', 'online_on_policy_trajectories'}
            eval_embedding_source='online_exploration_trajectories',
            recurrent=False, # recurrent or averaging encoder
            dump_eval_paths=True,
            render_eval_paths=False,
            render=False,
            task_idx_for_render=0,
        ),
        net_size=300,
        use_gpu=True,
        gpu_id=gpu,
    )

    exp_name = 'push'

    log_dir = '/mounts/output' if docker == 1 else 'output'
    experiment_log_dir = setup_logger(exp_name, variant=variant, exp_id='metaworld', base_log_dir=log_dir)

    # creates directories for pickle outputs of trajectories (point mass)
    pickle_dir = experiment_log_dir + '/eval_trajectories'
    pathlib.Path(pickle_dir).mkdir(parents=True, exist_ok=True)
    variant['algo_params']['output_dir'] = pickle_dir

    # debugging triggers a lot of printing
    DEBUG = 0
    os.environ['DEBUG'] = str(DEBUG)

    experiment(variant)

if __name__ == "__main__":
    main()