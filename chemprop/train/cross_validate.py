from collections import defaultdict
import csv
from logging import Logger
import os
from typing import Callable, Dict, List, Tuple, Union

import numpy as np

from .run_training import run_training
from chemprop.args import SklearnTrainArgs, TrainArgs
from chemprop.constants import TEST_SCORES_FILE_NAME, TRAIN_LOGGER_NAME
from chemprop.data import get_task_names
from chemprop.utils import create_logger, makedirs, timeit


@timeit(logger_name=TRAIN_LOGGER_NAME)
def cross_validate(args: Union[TrainArgs, SklearnTrainArgs],
                   train_func: Callable[[Union[TrainArgs, SklearnTrainArgs], Logger], Dict[str, List[float]]]
                   ) -> Tuple[float, float]:
    """
    Runs k-fold cross-validation.

    For each of k splits (folds) of the data, trains and tests a model on that split
    and aggregates the performance across folds.

    :param args: A :class:`~chemprop.args.TrainArgs` object containing arguments for
                 loading data and training the Chemprop model.
    :param train_func: Function which runs training.
    :return: A tuple containing the mean and standard deviation performance across folds.
    """
    logger = create_logger(name=TRAIN_LOGGER_NAME, save_dir=args.save_dir, quiet=args.quiet)
    info = logger.info if logger is not None else print

    # Initialize relevant variables
    init_seed = args.seed
    save_dir = args.save_dir
    args.task_names = get_task_names(
        path=args.data_path,
        smiles_column=args.smiles_column,
        target_columns=args.target_columns,
        ignore_columns=args.ignore_columns
    )

    # Run training on different random seeds for each fold
    all_scores = defaultdict(list)
    for fold_num in range(args.num_folds):
        info(f'Fold {fold_num}')
        args.seed = init_seed + fold_num
        args.save_dir = os.path.join(save_dir, f'fold_{fold_num}')
        makedirs(args.save_dir)
        model_scores = train_func(args, logger)
        for metric, scores in model_scores.items():
            all_scores[metric].append(scores)
    all_scores = dict(all_scores)

    # Convert scores to numpy arrays
    for metric, scores in all_scores.items():
        all_scores[metric] = np.array(scores)

    # Report results
    info(f'{args.num_folds}-fold cross validation')

    # Report scores for each fold
    for fold_num in range(args.num_folds):
        for metric, scores in all_scores.items():
            info(f'\tSeed {init_seed + fold_num} ==> test {metric} = {np.nanmean(scores[fold_num]):.6f}')

            if args.show_individual_scores:
                for task_name, score in zip(args.task_names, scores[fold_num]):
                    info(f'\t\tSeed {init_seed + fold_num} ==> test {task_name} {metric} = {score:.6f}')

    # Report scores across folds
    for metric, scores in all_scores.items():
        avg_scores = np.nanmean(scores, axis=1)  # average score for each model across tasks
        mean_score, std_score = np.nanmean(avg_scores), np.nanstd(avg_scores)
        info(f'Overall test {metric} = {mean_score:.6f} +/- {std_score:.6f}')

        if args.show_individual_scores:
            for task_num, task_name in enumerate(args.task_names):
                info(f'\tOverall test {task_name} {metric} = '
                     f'{np.nanmean(scores[:, task_num]):.6f} +/- {np.nanstd(scores[:, task_num]):.6f}')

    # Save scores
    with open(os.path.join(save_dir, TEST_SCORES_FILE_NAME), 'w') as f:
        writer = csv.writer(f)

        header = ['Task']
        for metric in args.metrics:
            header += [f'Mean {metric}', f'Standard deviation {metric}'] + \
                      [f'Fold {i} {metric}' for i in range(args.num_folds)]
        writer.writerow(header)

        for task_num, task_name in enumerate(args.task_names):
            row = []
            for metric, scores in all_scores.items():
                task_scores = scores[:, task_num]
                mean, std = np.nanmean(task_scores), np.nanstd(task_scores)
                row += [task_name, mean, std] + task_scores.tolist()
            writer.writerow(row)

    # Determine mean and std score of main metric
    avg_scores = np.nanmean(all_scores[args.metric], axis=1)
    mean_score, std_score = np.nanmean(avg_scores), np.nanstd(avg_scores)

    return mean_score, std_score


def chemprop_train() -> None:
    """Parses Chemprop training arguments and trains (cross-validates) a Chemprop model.

    This is the entry point for the command line command :code:`chemprop_train`.
    """
    cross_validate(args=TrainArgs().parse_args(), train_func=run_training)
