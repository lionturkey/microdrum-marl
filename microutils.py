import numpy as np
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import minimize, differential_evolution
from scipy.interpolate import interp1d
import envs
import os
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.vec_env import VecMonitor
from stable_baselines3.common.monitor import Monitor
import stable_baselines3 as sb3
import supersuit as ss
from pettingzoo.utils.conversions import parallel_to_aec


class PIDController:
    """
    A PID controller.
    Attributes:
        Kp: the proportional gain
        Ki: the integral gain
        Kd: the derivative gain
        max_rate: the maximum rate of change of the control signal
    """
    # minimized IAE: [0.07822899, 0.,         0.30242492]
    # evolution optimized: [0.07820128, 0.,         0.30870895]
    def __init__(self, Kp=.078, Ki=0, Kd=0.3, max_rate=1):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.max_rate = max_rate
        self.integral = 0.0
        self.err_prev = 0.0
        self.t_prev = 0.0
        self.deriv_prev = 0.0

    def update(self, measurement, setpoint):
        """
        Update the PID controller.
        Returns:
            the new control signal
        """
        err = setpoint - measurement
        del_t = 1
        self.integral += self.Ki * err * del_t
        self.deriv_prev = (err - self.err_prev) / (del_t)
        self.err_prev = err
        command = self.Kp * err + self.integral + self.Kd * self.deriv_prev
        command_sat = np.clip([command], -self.max_rate, self.max_rate)  # array
        return command_sat


def pid_loop(single_env):
    controller = PIDController()
    obs, _ = single_env.reset()
    done = False
    while not done:
        action = controller.update(obs["power"]*100,
                                   single_env.profile(single_env.time+1))
        obs, _, terminated, truncated, _ = single_env.step(action)
        if terminated or truncated:
            done = True
    single_env.render()


def tune_pid(profile, episode_length=200):
    run_folder = Path.cwd() / 'runs' / 'pid_train'
    run_folder.mkdir(exist_ok=True, parents=True)
    holos_env = envs.HolosSingle(profile=profile, episode_length=episode_length, run_path=run_folder, train_mode=False)

    def pid_objective(params):
        p_gain, i_gain, d_gain = params
        controller = PIDController(p_gain, i_gain, d_gain)
        obs, _ = holos_env.reset()
        done = False
        while not done:
            action = controller.update(obs["power"]*100,
                                       holos_env.profile(holos_env.time+1))
            obs, _, terminated, truncated, _ = holos_env.step(action)
            if terminated or truncated:
                done = True
            if obs['power'] > 1.2:
                fake_iae = 1_000 * obs['power'].item()
                print(f'IAE: {fake_iae}, gains: {p_gain}, {i_gain}, {d_gain}')
                return fake_iae
        holos_env.render()
        _, iae, _ = calc_metrics(holos_env.multi_env.history)
        print(f'IAE: {iae}, gains: {p_gain}, {i_gain}, {d_gain}')
        return iae
    
    # return differential_evolution(pid_objective, [(0, 1), (0, 1), (0, 1)])
    return minimize(pid_objective, [0.08, 0, 0.3], bounds=[(0, 5), (0, 5), (0, 5)])


def find_latest_file(folder_path: Path, pattern: str='*') -> Path:
    assert folder_path.exists()
    assert any(folder_path.glob(pattern)), f"No files match pattern '{pattern}' in folder '{folder_path}'"
    latest_file = sorted(folder_path.glob(pattern), key=os.path.getmtime, reverse=True)[0]
    assert latest_file.is_file(), f"Latest file '{latest_file}' is not a file"
    return latest_file


def load_history(history_path: Path):
    assert history_path.exists()
    history = pd.read_csv(history_path)
    assert history['desired_power'][0] == 1, 'steady state initial power value should be 100'
    assert history['drum_8'][0] == 77.8, 'steady state initial drum angle should be 77.8'
    return history


def calc_metrics(history: pd.DataFrame):
    assert history['time'][1] - history['time'][0] == 1, 'metric calculations assume 1 second timesteps'
    error = history['desired_power'] - history['actual_power']
    absolute_error = np.abs(error)
    mean_absolute_error = np.mean(absolute_error)
    integral_absolute_error = np.sum(absolute_error)
    drum_angles = history[['drum_1', 'drum_2', 'drum_3', 'drum_4', 'drum_5', 'drum_6', 'drum_7', 'drum_8']]
    drum_speeds = np.diff(drum_angles, axis=0)
    absolute_drum_speeds = np.abs(drum_speeds)
    control_effort = np.sum(absolute_drum_speeds)
    return mean_absolute_error, integral_absolute_error, control_effort


def plot_history(history: pd.DataFrame):
    plt.clf()
    plt.plot(history['time'], history['actual_power'])
    plt.plot(history['time'], history['desired_power'])
    plt.xlabel('Time (s)')
    plt.ylabel('Power (SPU)')
    plt.title('Power vs. Time')
    plt.show()


def train_rl(env_type, env_kwargs, total_timesteps=2_000_000, n_envs=10):
    run_folder = env_kwargs['run_path']
    model_folder = run_folder / 'models/'
    model_folder.mkdir(exist_ok=True)
    log_dir = run_folder / 'logs/'
    vec_env = make_vec_env(env_type, n_envs=n_envs,
                            env_kwargs=env_kwargs)
    vec_env = VecMonitor(vec_env,
                        filename=str(log_dir / 'vec'))
    model = sb3.PPO('MultiInputPolicy', vec_env, verbose=1,
                    tensorboard_log=str(log_dir),
                    device='cpu')
    eval_env = env_type(**env_kwargs)
    eval_env = Monitor(eval_env, filename=str(log_dir / 'eval'))
    eval_freq = 10_000 / n_envs
    eval_freq = round(eval_freq, -3)  # round to nearest 1000 to eval every ~10k steps
    eval_callback = EvalCallback(eval_env=eval_env,
                                    best_model_save_path=str(model_folder),
                                    log_path=str(log_dir),
                                    deterministic=True,
                                    eval_freq=eval_freq)
    model.learn(total_timesteps=total_timesteps, callback=eval_callback, progress_bar=True)


def rl_control_loop(model, env):
    obs, _ = env.reset()
    done = False
    while not done:
        action, _states = model.predict(obs, deterministic=True)
        obs, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            done = True
    env.render()


def test_trained_rl(env_type: type, env_kwargs: dict) -> pd.DataFrame:
    run_folder = env_kwargs['run_path']
    model_folder = run_folder / 'models/'
    model_path = find_latest_file(model_folder, pattern='*.zip')
    model = sb3.PPO.load(model_path, device='cpu')
    test_env = env_type(**env_kwargs)
    rl_control_loop(model, test_env)
    history_path = find_latest_file(run_folder, pattern='run_history*.csv')
    history = load_history(history_path)
    mae, iae, control_effort = calc_metrics(history)
    print(f'{run_folder.name} - MAE: {mae}, IAE: {iae}, Control Effort: {control_effort}')
    return history


def train_marl(env_type, env_kwargs, total_timesteps=40_000_000, n_envs=10):
    run_folder = env_kwargs['run_path']
    model_folder = run_folder / 'models/'
    model_folder.mkdir(exist_ok=True)
    log_dir = run_folder / 'logs/'
    log_dir.mkdir(exist_ok=True)

    env = env_type(**env_kwargs)
    env = ss.pettingzoo_env_to_vec_env_v1(env)
    env = ss.concat_vec_envs_v1(env, n_envs, base_class="stable_baselines3")
    vec_log_folder = run_folder / 'logs/vec'
    env = VecMonitor(env, filename=str(vec_log_folder))
    # the model will be saved every 6envs * 8drums * 20_000 = 960_000 timesteps
    save_freq = 1_000_000 / (8 * n_envs)
    save_freq = round(save_freq, -3) # round to nearest 1000 to get saves every ~1 mil timesteps
    checkpoint_callback = CheckpointCallback(save_freq=save_freq, save_path=str(model_folder),
                                             name_prefix='ppo_marl')
    model = sb3.PPO("MultiInputPolicy", env, verbose=1, tensorboard_log=str(log_dir), device='cpu')
    model.learn(total_timesteps=total_timesteps, callback=checkpoint_callback, progress_bar=True)


def marl_control_loop(model, env):
    env = parallel_to_aec(env)
    env.reset()
    for agent in env.agent_iter():
        obs, reward, terminated, truncated, info = env.last()
        if terminated or truncated:
            break
        else:
            action, _ = model.predict(obs, deterministic=True)
            env.step(action)
    env.render()

def test_trained_marl(env_type, env_kwargs):
    run_folder = env_kwargs['run_path']
    model_folder = run_folder / 'models/'
    model_path = find_latest_file(model_folder, pattern='*.zip')
    model = sb3.PPO.load(model_path, device='cpu')
    test_env = env_type(**env_kwargs)
    marl_control_loop(model, test_env)
    history_path = find_latest_file(run_folder, pattern='run_history*.csv')
    history = load_history(history_path)
    mae, iae, control_effort = calc_metrics(history)
    print(f'{run_folder.name} - MAE: {mae}, IAE: {iae}, Control Effort: {control_effort}')
    return history


if __name__ == '__main__':
    training_profile = interp1d([  0,  20, 30, 35, 60, 100, 120, 125, 140, 160, 180, 200], # times (s)
                                [100, 100, 90, 90, 55,  55,  65,  65,  80,  80,  95,  95]) # power (SPU)
    result = tune_pid(training_profile)
    print('Tuned PID parameters:')
    print(f'P gain: {result.x[0]}, I gain: {result.x[1]}, D gain: {result.x[2]}')