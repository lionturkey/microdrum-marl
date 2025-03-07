import stable_baselines3 as sb3
import numpy as np
import pandas as pd
from pathlib import Path
import argparse
import matplotlib
import matplotlib.pyplot as plt
import envs
import microutils
from scipy.interpolate import interp1d


def main(args):
    # create interpolated power profiles
    training_profile = interp1d([  0,  15, 30, 70, 100, 140, 160, 195, 200], # times (s)
                                [100, 100, 80, 55,  55,  70,  70,  80,  80]) # power (SPU)
    lowpower_profile = interp1d([  0,   5, 100, 200], # times (s)
                                [100, 100,  40,  90]) # power (SPU)
    longtest_profile = interp1d([  0,  2000, 3000, 3500, 6000, 10000, 12000, 12500, 14000, 16000, 18000, 20000], # times (s)
                                [100,   100,   90,   90,   45,    45,    65,    65,    80,  80,  95,  95]) # power (SPU)
    testing_profile = interp1d([  0,  10, 70, 100, 115, 125, 150, 180, 200], # times (s)
                               [100, 100, 45, 45,   65,  65,  50,  80,  80]) # power (SPU)

    match args.test_profile:
        case 'longtest':
            test_profile = longtest_profile
            episode_length = 20000
        case 'lowpower':
            test_profile = lowpower_profile
            episode_length = 200
        case 'training':
            test_profile = training_profile
            episode_length = 200
        case _:
            test_profile = testing_profile
            episode_length = 200

    training_kwargs = {'profile': training_profile,
                      'episode_length': 200,
                      'train_mode': True}
    testing_kwargs = {'profile': test_profile,
                     'episode_length': episode_length,
                     'valid_maskings': (args.disabled_drums,),
                     'train_mode': False}


    #############################
    # Single Action RL Training #
    #############################
    single_folder = Path.cwd() / 'runs' / 'single_action_rl'
    single_folder.mkdir(exist_ok=True, parents=True)
    model_folder = single_folder / 'models/'
    if not model_folder.exists():  # if a model has already been trained, don't re-train
        training_kwargs['run_path'] = single_folder
        microutils.train_rl(envs.HolosSingle, training_kwargs,
                            total_timesteps=args.timesteps, n_envs=args.n_envs)

    #########################################
    # Single Action Innoculated RL Training #
    #########################################
    innoculated_folder = Path.cwd() / 'runs' / 'single_action_innoculated'
    innoculated_folder.mkdir(exist_ok=True, parents=True)
    model_folder = innoculated_folder / 'models/'
    if not model_folder.exists():  # if a model has already been trained, don't re-train
        training_kwargs['run_path'] = innoculated_folder
        training_kwargs['noise'] = 0.02  # 2 SPU standard deviation of measurement noise
        microutils.train_rl(envs.HolosSingle, training_kwargs,
                            total_timesteps=args.timesteps, n_envs=args.n_envs)

    ##########################
    # Multi Drum RL Training #
    ##########################
    multi_folder = Path.cwd() / 'runs' / 'multi_action_rl'
    multi_folder.mkdir(exist_ok=True, parents=True)
    model_folder = multi_folder / 'models/'
    if not model_folder.exists():  # if a model has already been trained, don't re-train
        training_kwargs['run_path'] = multi_folder
        # training_kwargs['valid_maskings'] = (0,1,2,3)  # disable up to three drums at random
        microutils.train_rl(envs.HolosMulti, training_kwargs,
                            total_timesteps=args.timesteps, n_envs=args.n_envs)

    ######################################
    # Multi Drum RL (symmetric) Training #
    ######################################
    symmetric_folder = Path.cwd() / 'runs' / 'multi_action_rl_symmetric'
    symmetric_folder.mkdir(exist_ok=True, parents=True)
    model_folder = symmetric_folder / 'models/'
    if not model_folder.exists():  # if a model has already been trained, don't re-train
        training_kwargs['run_path'] = symmetric_folder
        # training_kwargs['valid_maskings'] = (0,1,2,3)  # disable up to three drums at random
        microutils.train_rl(envs.HolosMulti,
                            {**training_kwargs,
                             'symmetry_reward': True},
                            total_timesteps=args.timesteps, n_envs=args.n_envs)

    #################
    # MARL Training #
    #################
    marl_folder = Path.cwd() / 'runs' / 'marl'
    marl_folder.mkdir(exist_ok=True, parents=True)
    model_folder = marl_folder / 'models/'
    if not model_folder.exists():
        training_kwargs['run_path'] = marl_folder
        # training_kwargs['valid_maskings'] = (0,1,2,3)  # disable up to three drums at random
        microutils.train_marl(envs.HolosMARL, training_kwargs,
                              total_timesteps=(args.timesteps * 8), n_envs=args.n_envs)


    ####################
    # Plotting Figures #
    ####################
    graph_path = Path.cwd() / 'graphs'
    graph_path.mkdir(exist_ok=True, parents=True)

    # start with the PID benchmark, creating its own run folder
    pid_folder = Path.cwd() / 'runs' / 'pid'
    pid_folder.mkdir(exist_ok=True, parents=True)
    training_kwargs['run_path'] = pid_folder
    pid_train_history = microutils.test_pid(envs.HolosSingle, training_kwargs)

    # Example profiles to validate environment and show train profile with PID
    plot_path = graph_path / '1a_PID-train-power.png'
    data_list = [(pid_train_history, 'desired_power', 'desired power'),
                 (pid_train_history, 'actual_power', 'actual power')]
    microutils.plot_history(plot_path, data_list, 'Power (SPU)')

    plot_path = graph_path / '1b_PID-train-temp.png'
    data_list = [(pid_train_history, 'Tf', 'fuel temp'),
                 (pid_train_history, 'Tm', 'moderator temp'),
                 (pid_train_history, 'Tc', 'coolant temp')]
    microutils.plot_history(plot_path, data_list, 'Temperature (K)')

    # TODO redo from scratch
    plot_path = graph_path / '1c_PID-train-diff.png'
    data_list = [(pid_train_history, 'diff', 'power difference')]
    microutils.plot_history(plot_path, data_list, 'Power Difference (SPU)')

    # TODO redo from scratch
    plot_path = graph_path / '1d_PID-train-angle.png'
    data_list = [(pid_train_history, 'drum_1', 'all drums')]
    microutils.plot_history(plot_path, data_list, 'Control Drum Position (°)')


    # gather test histories
    #######################
    print(f'testing with {args.test_profile}:')
    pid_test_history = microutils.test_pid(envs.HolosSingle, {**testing_kwargs,
                                                              'run_path': pid_folder})
    single_test_history = microutils.test_trained_rl(envs.HolosSingle, {**testing_kwargs,
                                                                        'run_path': single_folder,})
    multi_test_history = microutils.test_trained_rl(envs.HolosMulti, {**testing_kwargs,
                                                                      'run_path': multi_folder})
    symmetric_test_history = microutils.test_trained_rl(envs.HolosMulti,
                                                        {**testing_kwargs,
                                                        'run_path': symmetric_folder,
                                                        'symmetry_reward': True,
                                                        'train_mode': True})  # necessary to cutoff runaway power
    marl_test_history = microutils.test_trained_marl(envs.HolosMARL, {**testing_kwargs,
                                                                      'run_path': marl_folder})
                                                
    # plot comparisons
    ###################
    plot_path = graph_path / f'2_{args.test_profile}-power.png'
    data_list = [(pid_test_history, 'desired_power', 'desired power'),
                 (pid_test_history, 'actual_power', 'pid'),
                 (single_test_history, 'actual_power', 'rl')]
    microutils.plot_history(plot_path, data_list, 'Power (SPU)')

    plot_path = graph_path / f'2_{args.test_profile}-diff.png'
    data_list = [(pid_test_history, 'diff', 'pid'),
                 (single_test_history, 'diff', 'rl')]
    microutils.plot_history(plot_path, data_list, 'Power Difference (SPU)')


    plot_path = graph_path / f'3_{args.test_profile}-power.png'
    data_list = [(pid_test_history, 'desired_power', 'desired power'),
                 (multi_test_history, 'actual_power', 'multi-action'),
                 (symmetric_test_history, 'actual_power', 'symmetric'),
                 (marl_test_history, 'actual_power', 'marl')]
    microutils.plot_history(plot_path, data_list, 'Power (SPU)')

    plot_path = graph_path / f'3_{args.test_profile}-diff.png'
    data_list = [(multi_test_history, 'diff', 'multi-action'),
                #  (symmetric_test_history, 'diff', 'symmetric'),
                 (marl_test_history, 'diff', 'marl')]
    microutils.plot_history(plot_path, data_list, 'Power Difference (SPU)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--plotting', action='store_true',  # TODO remove, unused
                        help='Plot interactive, intermediate results')
    parser.add_argument('-p', '--test_profile', type=str, default='test',
                        help='Profile to use for testing (test, train, longtest, lowpower)')
    parser.add_argument('-t', '--timesteps', type=int, default=2_000_000,
                        help='Number of timesteps to train for')
    parser.add_argument('-d', '--disabled_drums', type=int, default=0,
                        help='Number of drums to disable during testing')
    parser.add_argument('-n', '--n_envs', type=int, default=10,
                        help='Number of environments to use for training')
    args = parser.parse_args()
    main(args)
