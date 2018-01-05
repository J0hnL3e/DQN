import theano
import theano.tensor as T

import gym

import numpy as np
import matplotlib.pyplot as plt

from six.moves import cPickle

# constants
floatX = np.float64
small = 1e-7

# MODEL
def conv_weight_he(o, i, w, h):
    w = (2 * np.random.randn(o, i, w, h) / (i * w * h)).astype(floatX)

    return theano.shared(w)

def fc_init_he(i, o):
    w = (2 * np.random.randn(i, o) / (i)).astype(floatX)

    return theano.shared(w)

def shared(x):
    return theano.shared(x.astype(floatX))

class DQN:
    def __init__(self, network, memory_cap = 50000, epsilon_start = 1, epsilon_end = 0.1, epsilon_decay = 0.00001, discount = 0.99):
        self.network = network

        self.memory_cap = memory_cap
        self.memory = []

        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_end
        self.epsilon_decay = epsilon_decay

        self.discount = discount

        self.get_Q = self.network.get_Q

    def step(self, env, observation, keep_in_memory = True):
        rand = np.random.uniform()

        if (rand < self.epsilon):
            action = np.random.choice([0, 1, 2, 3])
        else:
            Q = self.get_Q(observation)[0]

            # Get action that maximizes the Q value, so we perform argmax along the last axis
            action = np.argmax(Q)

        new_info = env.step(action)

        # Bellman equation for DQN is: Q_t = R(s, a) + gamma * max_a(Q(s', a))
        # So we need to keep all the information for the transition

        #             s            s'                       a       r            done (for terminal state)
        transition = (observation, preprocess(new_info[0]), action, new_info[1], new_info[2])

        if keep_in_memory:
            self.memory.append(transition)

            if len(self.memory) > self.memory_cap:
                # Delete a random memory
                del self.memory[np.random.randint(0, len(self.memory))]
                #del self.memory[0]

        self.epsilon = np.maximum(self.epsilon - self.epsilon_decay, self.epsilon_min)

        return new_info, transition

    def train(self, target_net, lr = 0.00025, bs = 32):
        """
            train(self, target, lr, bs) -> loss

            trains the DQN agent with the bellman equation.
        """

        # Accumulate bs transitions
        transitions = self.sample_transition(bs)

        # Set targets
        states = []
        targets = []

        for t in transitions:
            s, s_, a, r, terminal = t

            # get current q_values for s and s'
            # We get Q values for state s with current approximator because we're training the current approximator, so we want matching Q values, but we get Q values for state s_ with target network because we're using it as our fixed baseline
            Q = self.get_Q(s)[0]
            Q_ = target_net.get_Q(s_)[0]

            target = np.copy(Q)

            if terminal:
                target[a] = r
            else:
                target[a] = r + self.discount * np.max(Q_)

            # 1 x actions
            targets.append(np.expand_dims(target, axis = 0))
            states.append(s)

        # bs x actions, bs x input_size
        targets = np.concatenate(targets, axis = 0)
        states = np.concatenate(states, axis = 0)

        loss = self.network.train_Q(states, targets, lr)

        return loss

    def sample_transition(self, bs = 1):
        """
            returns an array of transitions
        """

        return [self.memory[np.random.randint(0, len(self.memory))] for b in range (bs)]

    def copy_weights(self, approximator):
        """
            copies weights from current DQN agent to another approximator, for target network
        """

        for w, w_ in zip(approximator.get_weights(), self.network.get_weights()):
            w.set_value(w_.get_value())

class Approximator:
    def __init__(self, observation_type):
        self.weights = {
            "fc1" : fc_init_he(8, 128),
            "fc2" : fc_init_he(128, 128),
            "fc3" : fc_init_he(128, 4)
        }

        self.observation = observation_type
        self.targets = T.matrix()               # self.targets will 99.99% of the time be bs x actions, so we'll just assume it's that way
        self.lr = T.scalar()

        Q = self.forward(self.observation)

        # squared error
        loss = huber_loss(self.targets, Q)

        updates = RMSprop(cost = loss, params = self.get_weights(), lr = self.lr)

        self.get_Q = theano.function(inputs = [self.observation], outputs = Q)
        self.train_Q = theano.function(inputs = [self.observation, self.targets, self.lr], outputs = loss, updates = updates)

    def forward(self, observation):
        """
            forward(self, observation) -> Q

            `forward` is the execution of the Q value approximator, and outputs a Q value for each action given the observation.

            observation -> bs x *
            Q           -> bs x actions
        """

        fc1 = T.tanh(T.dot(observation, self.weights['fc1']))
        fc2 = T.tanh(T.dot(fc1, self.weights['fc2']))
        Q = T.dot(fc2, self.weights['fc3'])

        return Q

    def get_weights(self):
        return [self.weights['fc1'], self.weights['fc2'], self.weights['fc3']]

def RMSprop(cost, params, lr=0.001, rho=0.9, epsilon=1e-6):
    grads = T.grad(cost=cost, wrt=params)
    updates = []
    for p, g in zip(params, grads):
        acc = theano.shared(p.get_value() * 0.)
        acc_new = rho * acc + (1 - rho) * g ** 2
        gradient_scaling = T.sqrt(acc_new + epsilon)
        g = g / gradient_scaling
        updates.append((acc, acc_new))
        updates.append((p, p - lr * g))
    return updates

def huber_loss(target, output, delta = 0.1):
    d = target - output

    l1 = (d ** 2)/2.
    l2 = delta * (abs(d) - delta / 2.)

    lf = T.switch(abs(d) <= delta, l1, l2)

    return lf.sum()

def preprocess(observation):
    return np.expand_dims(observation, axis = 0)

def main():
    target = Approximator(observation_type = T.matrix())
    approximator = Approximator(observation_type = T.matrix())
    dqn = DQN(network = approximator)

    env = gym.make("LunarLander-v2")

    # Initialize target approximator with current
    dqn.copy_weights(target)

    total_ts = 0

    episodes = 100000
    for episode in range (episodes):
        done = False
        ts = 0
        r = 0

        observation = preprocess(env.reset())
        while not done and ts < 5000:
            (observation, reward, done, info), _ = dqn.step(env, observation)
            observation = preprocess(observation)

            r += reward

            if episode % 10 == 0:
                env.render()

            if total_ts % 1000 == 0:
                # Update target network
                #print(target.get_weights()[0].get_value())
                dqn.copy_weights(target)
                #print(target.get_weights()[0].get_value())

            if total_ts % 10000 == 0:
                print("SAVING WEIGHTS")
                weight = open("dqn_lunarlander" + str(total_ts) + ".w", 'wb')
                for w in dqn.network.get_weights():
                    cPickle.dump(w, weight, protocol = cPickle.HIGHEST_PROTOCOL)

                weight.close()

            if (len(dqn.memory) > 2000 and total_ts % 5 == 0):
                dqn.train(target)

            total_ts += 1
            ts += 1

        print("Reward: " + str(r) + " | Epsilon: " + str(dqn.epsilon))

if __name__ == "__main__":
    main()
