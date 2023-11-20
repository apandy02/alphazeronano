"""
Author: Aryaman Pandya
File contents: Implementation of our AlphaZero Nano agent.
This file contains the training code and supporting functions
required to enable training through self play.
"""
import copy

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from Game import Game
from mcts import apv_mcts


class AlphaZeroNano:
    """
    Class implementation of AlphaZero agent.
    """

    def __init__(
            self,
            num_simulations: int,
            optimizer,
            game: Game,
            c_uct: float) -> None:

        self.c_parameter = c_uct
        self.num_simulations = num_simulations
        self.optimizer = optimizer

        # notes: dynamics differences. Each game object instance 
        # is a game instance. Need to figure out how to re-initialize..?
        self.game = game

    def train(self,
              neural_network: torch.nn.Module,
              train_batch_size: int,
              num_epochs: int,
              num_episodes: int) -> torch.nn.Module:
        """
        Main agent trainer. Combines self play with MCTS and 
        network retraining based on this experience to develop 
        our agent. Returns trained neural network.

        Args:
            neural_network (torch.nn.Module) 
            train_batch_size (int)
            num_epochs (int)
            num_episodes (int)

        Returns:
            current_network (torch.nn.Module)
        """
        current_network = neural_network

        for _ in range(num_epochs):
            train_episodes = self.self_play(
                model=current_network,
                num_episodes=num_episodes
            )
            # keep a copy of the current network for evaluation
            old_network = copy.deepcopy(current_network)

            self.retrain_nn(
                neural_network=current_network,
                train_data=train_episodes,
                train_batch_size=train_batch_size
            )
            # note: figure out if the following assignment makes sense
            current_network = self.evaluate_networks(
                current_network,
                old_network,
                10
            )

        return current_network

    def evaluate_networks(self,
                          network_a: torch.nn.Module,
                          network_b: torch.nn.Module,
                          num_games: int,
                          threshold=0.6) -> torch.nn.Module:
        """
        Evaluate networks. Makes two networks play a specified 
        number of games against one another and returns the second
        network if it beats the first beyond some threshold %

        Args:
            network_a (torch.nn.Module) 
            network_b (torch.nn.Module)
            num_games (int)
            threshold (float)

        Returns:
            network (torch.nn.Module)
        """
        network_a_wins = 0

        for _ in range(num_games):
            network_a_result = self.play_game(network_a, network_b)
            if network_a_result > 0:
                network_a_wins += 1

        win_rate = network_a_wins / num_games

        if win_rate > threshold:
            return network_a

        return network_b

    def retrain_nn(self,
                   neural_network: torch.nn.Module,
                   train_data: list,
                   train_batch_size: int) -> None:
        """
        Neural network trainer function. 

        Args:
            neural_network (torch.nn.Module) 
            train_data (list)
            train_batch_size (int)

        Returns:
            N/A
        """
        policy_loss_fn = torch.nn.CrossEntropyLoss()
        value_loss_fn = torch.nn.MSELoss()

        dataloader = self.batch_episodes(
            train_data, batch_size=train_batch_size
        )

        for x_train, policy_train, value_train in dataloader:
            policy_pred, value_pred = neural_network.predict(x_train)

            policy_loss = policy_loss_fn(policy_train, policy_pred)
            value_loss = value_loss_fn(value_train, value_pred)
            combined_loss = policy_loss + value_loss

            self.optimizer.zero_grad()
            combined_loss.backward()
            self.optimizer.step()

    def play_game(self,
                  network_a: torch.nn.Module,
                  network_b: torch.nn.Module) -> bool:
        """
        Makes two network play a game against one another.
        Args:
            network_a (torch.nn.Module)
            network_b (torch.nn.Module)
        Returns:
            result (bool)
        """
        game_state = self.game.getInitBoard()
        player = 1

        while not game_state.getGameEnded():
            if player == 1:
                policy, _ = network_a.predict(game_state)
            else:
                policy, _ = network_b.predict(game_state)

            _, action = torch.max(policy, dim=-1)

            game_state, player = game_state.getNextState(
                game_state,
                player,
                action
            )

        if player == -1:
            return game_state.getGameEnded()

        return game_state.getGameEnded()

    def self_play(self, model: torch.nn.Module, num_episodes: int):
        """
        Self play. Simulates number of episodes using MCTS and a given
        neural network. 

        Args:
            model (torch.nn.Module)
            num_episodes (int)

        Returns:
            episodes (list)
        """
        train_episodes = []

        for _ in range(num_episodes):
            game_states = []
            game_state = self.game.getInitBoard()
            player = 1
            while not self.game.getGameEnded(board=game_state, player=player):
                policy = apv_mcts(
                    game=self.game,
                    root_state=game_state,
                    model=model,
                    num_iterations=self.num_simulations,
                    c=self.c_parameter,
                )

                game_states.append((game_state, policy))

                action = np.random.choice(
                    np.arange(self.game.getActionSize()),
                    p=policy
                )

                game_state, player = game_state.getNextState(
                    game_state,
                    player,
                    action)

            game_result = game_state.getGameEnded()
            for state, policy in game_states:
                train_episodes.append((state, policy, game_result))

        return train_episodes

    def batch_episodes(self, train_data: list, batch_size: int):
        """
        Batch episodes: given a list of experience, unpacks and
        converts to torch loaders.

        Args:
            train_data (list)
            batch_size (int)

        Returns:
            dataloader (TensorDataset)
        """
        states, policies, results = zip(*train_data)
        states_tensor = torch.tensor(states, dtype=torch.float32)
        policies_tensor = torch.tensor(policies, dtype=torch.float32)
        results_tensor = torch.tensor(results, dtype=torch.float32)

        dataset = TensorDataset(states_tensor, policies_tensor, results_tensor)
        dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

        return dataloader
