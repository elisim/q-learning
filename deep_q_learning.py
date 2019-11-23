import random
import numpy as np
from collections import deque
from tqdm import tqdm
import datetime
import statistics

# turn off warnings and tensorflow logging  
import tensorflow as tf

from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.optimizers import Adam


import warnings
warnings.filterwarnings("ignore")

__all__ = ['DQNAgent']


class DQNAgent:
    """
    Basic DQN algorithm
    """
    def __init__(self,
                 env,
                 gamma=0.95,
                 epsilon=1.0,
                 min_epsilon=0.01,
                 epsilon_decay=0.995,
                 learning_rate=0.001,
                 experience_replay_size=2000,
                 steps_update_target_model=32,
                 num_layers=3):
        """
        :param env: Open AI env
        :param gamma: discount factor 𝛾,
        :param epsilon: initial epsilon
        :param min_epsilon: min epsilon rate (end of decaying)
        :param epsilon_decay: decay rate for decaying epsilon-greedy probability
        :param learning_rate: learning rate for neural network optimizer
        :param experience_replay_size: experience replay size
        :param steps_update_target_model: num of steps to update the target model (𝜃− <- 𝜃)
        :param num_layers: number of layers to the model (could be 3 or 5)
        """
        self.env = env
        self.state_size = env.observation_space.shape[0]
        self.action_size = env.action_space.n
        self.experience_replay = deque(maxlen=experience_replay_size)
        self.gamma = gamma
        self.epsilon = epsilon
        self.min_epsilon = min_epsilon
        self.epsilon_decay = epsilon_decay
        self.learning_rate = learning_rate
        self.steps_update_target_model = steps_update_target_model
        self.num_layers = num_layers
        self.q_value_model = self._build_model()  # predicting the q-value (using parameters 𝜃)
        self.target_model = self._build_model()  # computing the targets (using an older set of parameters 𝜃−)

        self._log_dir = "logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self._tensorboard_callback = tf.keras.callbacks.TensorBoard(log_dir=self._log_dir, histogram_freq=1)
        self._file_writer = tf.summary.create_file_writer(self._log_dir + "/metrics")
        self._file_writer.set_as_default()
        self._last_100_rewards = deque(maxlen=100)

    def _build_model(self):
        """
        Neural Network for Q-value approximation.
        The network takes a state as an input (or a minibatch of states)
        and output the predicted q-value of each action for that state.
        """
        model = Sequential()
        model.add(Dense(units=32, input_dim=self.state_size, activation='relu'))
        model.add(Dense(units=32, activation='relu'))
        model.add(Dense(units=32, activation='relu'))
        model.add(Dense(units=32, activation='relu'))
        if self.num_layers == 5:
            model.add(Dense(units=32, activation='relu'))
            model.add(Dense(units=32, activation='relu'))
        model.add(Dense(units=self.action_size, activation='linear'))
        model.compile(loss='mse', optimizer=Adam(lr=self.learning_rate))
        return model

    def _sample_action(self, state):
        """
        choose an action with decaying 𝜀-greedy method, given state 'state'
        """
        if random.uniform(0, 1) < self.epsilon:
            return self.env.action_space.sample()

        q_values = self.q_value_model.predict(state)[0]  # predict q-value given state
        return np.argmax(q_values)  # return action with max q-value

    def _sample_batch(self, batch_size):
        """
        sample a minibatch randomly from the experience_replay in 'batch_size' size
        """
        return random.sample(self.experience_replay, batch_size)

    def _replay(self, batch_size, step_number):
        """
        sample random minibatch, update y, and perform gradient descent step
        """
        # wait for 'experience_replay' to contain at least 'batch_size' transitions
        if len(self.experience_replay) <= batch_size:
            return

        minibatch = self._sample_batch(batch_size)

        states_in_batch = []
        target_in_batch = []
        for state, action, reward, next_state, done in minibatch:
            if done:  # for terminal transition
                target = reward
            else:  # for non-terminal transition
                target = (reward + self.gamma*np.max(self.target_model.predict(next_state)[0]))

            # update y
            target_f = self.q_value_model.predict(state)
            target_f[0][action] = target

            states_in_batch.append(state[0])
            target_in_batch.append(target_f[0])

        # perform a gradient descent for entire batch
        self.q_value_model.fit(np.array(states_in_batch),
                               np.array(target_in_batch),
                               batch_size=batch_size,
                               epochs=step_number + 1,
                               initial_epoch=step_number,
                               verbose=0,
                               use_multiprocessing=True,
                               callbacks=[self._tensorboard_callback])

        # decaying epsilon-greedy probability
        self.epsilon = max(self.min_epsilon, self.epsilon*self.epsilon_decay)

    def _correct_state_size(self, state):
        """
        correct state size from (state_size,) to (1, state_size) for the network
        """
        return np.reshape(state, [1, self.state_size])

    def train_agent(self,
                    episodes,
                    steps_per_episode,
                    batch_size,
                    ):
        """
        train the agent with the DQN algorithm

        :param episodes: number of episodes
        :param steps_per_episode: max steps per episode
        :param batch_size: batch size
        """
        steps_till_update = 1  # count number of steps to update the target network
        total_steps = 1

        for i in tqdm(range(1, episodes+1)):
            # get initial state s
            state = self._correct_state_size(self.env.reset())

            reward_in_episode = 0
            for step in range(1, steps_per_episode):
                # select action using 𝜀-greedy method
                action = self._sample_action(state)

                # execute action in emulator and observe reward, next state, and episode termination signal
                next_state, reward, done, _ = self.env.step(action)
                next_state = self._correct_state_size(next_state)

                reward_in_episode += reward

                # store transition in replay memory
                self.experience_replay.append((state, action, reward, next_state, done))

                # update current state to next state
                state = next_state

                # break episode on terminal state
                if done:
                    break

                # sample random minibatch, update y, and perform gradient descent step
                self._replay(batch_size, total_steps)

                # every 'steps_update_target_model' steps, update target network (𝜃− <- 𝜃)
                if steps_till_update % self.steps_update_target_model == 0:
                    self.target_model.set_weights(self.q_value_model.get_weights())
                    steps_till_update = 1

                steps_till_update += 1
                total_steps += 1

            tf.summary.scalar('reward', data=reward_in_episode, step=i)
            self._last_100_rewards.append(reward_in_episode)
            print(f'episode reward: {reward_in_episode} reward of last 100 episodes: {statistics.mean(self._last_100_rewards)}')

    def test_agent(self, episodes):
        """
        test the agent on a new episode with the trained model
        :param episodes: number of episodes
        """
        for _ in range(episodes):
            state = self.env.reset()
            done = False

            while not done:
                state = self._correct_state_size(state)
                action = np.argmax(self.q_value_model.predict(state)[0])
                state, reward, done, _ = self.env.step(action)
                self.env.render()
        self.env.close()
