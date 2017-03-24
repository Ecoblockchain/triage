from triage.scoring import ModelScorer, generate_binary_at_x
import testing.postgresql

from sqlalchemy import create_engine
from triage.db import ensure_db
from tests.utils import fake_labels, fake_trained_model
from triage.storage import InMemoryModelStorageEngine
import datetime


def always_half(predictions_proba, predictions_binary, labels, parameters):
    return 0.5


def test_model_scoring_early_warning():
    with testing.postgresql.Postgresql() as postgresql:
        db_engine = create_engine(postgresql.url())
        ensure_db(db_engine)
        metric_groups = [{
            'metrics': ['precision@',
                        'recall@',
                        'true positives@',
                        'true negatives@',
                        'false positives@',
                        'false negatives@'],
            'thresholds': {
                'percentiles': [5.0, 10.0],
                'top_n': [5, 10]
            }
        }, {
            'metrics': ['f1',
                        'mediocre',
                        'accuracy',
                        'roc_auc',
                        'average precision score'],
        }, {
            'metrics': ['fbeta@'],
            'parameters': [{'beta': 0.75}, {'beta': 1.25}]
        }]

        custom_metrics = {'mediocre': always_half}

        model_scorer = ModelScorer(metric_groups, db_engine, custom_metrics)

        trained_model, model_id = fake_trained_model(
            'myproject',
            InMemoryModelStorageEngine('myproject'),
            db_engine
        )

        labels = fake_labels(5)
        as_of_date = datetime.date(2016, 5, 5)
        model_scorer.score(
            trained_model.predict_proba(labels)[:, 1],
            trained_model.predict(labels),
            labels,
            model_id,
            as_of_date,
            as_of_date,
            '1y'
        )

        # assert
        # that all of the records are there
        records = [
            row[0] for row in
            db_engine.execute(
                '''select distinct(metric || parameter)
                from results.evaluations
                where model_id = %s and
                evaluation_start_time = %s order by 1''',
                (model_id, as_of_date)
            )
        ]
        assert records == [
            'accuracy',
            'average precision score',
            'f1',
            'false negatives@10.0_pct',
            'false negatives@10_abs',
            'false negatives@5.0_pct',
            'false negatives@5_abs',
            'false positives@10.0_pct',
            'false positives@10_abs',
            'false positives@5.0_pct',
            'false positives@5_abs',
            'fbeta@0.75_beta',
            'fbeta@1.25_beta',
            'mediocre',
            'precision@10.0_pct',
            'precision@10_abs',
            'precision@5.0_pct',
            'precision@5_abs',
            'recall@10.0_pct',
            'recall@10_abs',
            'recall@5.0_pct',
            'recall@5_abs',
            'roc_auc',
            'true negatives@10.0_pct',
            'true negatives@10_abs',
            'true negatives@5.0_pct',
            'true negatives@5_abs',
            'true positives@10.0_pct',
            'true positives@10_abs',
            'true positives@5.0_pct',
            'true positives@5_abs'
        ]


def test_model_scoring_inspections():
    with testing.postgresql.Postgresql() as postgresql:
        db_engine = create_engine(postgresql.url())
        ensure_db(db_engine)
        metric_groups = [{
            'metrics': ['precision@', 'recall@'],
            'thresholds': {
                'percentiles': [5.0, 10.0],
                'top_n': [5, 10]
            }
        }]

        model_scorer = ModelScorer(metric_groups, db_engine)

        trained_model, model_id = fake_trained_model(
            'myproject',
            InMemoryModelStorageEngine('myproject'),
            db_engine
        )

        labels = fake_labels(5)
        evaluation_start = datetime.datetime(2016, 4, 1)
        evaluation_end = datetime.datetime(2016, 7, 1)
        prediction_frequency = '1d'
        model_scorer.score(
            trained_model.predict_proba(labels)[:, 1],
            trained_model.predict(labels),
            labels,
            model_id,
            evaluation_start,
            evaluation_end,
            prediction_frequency
        )

        # assert
        # that all of the records are there
        results = db_engine.execute(
            '''select distinct(metric || parameter) from results.evaluations
            where model_id = %s and evaluation_start_time = %s order by 1''',
            (model_id, evaluation_start)
        )
        records = [
            row[0] for row in results
        ]
        assert records == [
            'precision@10.0_pct',
            'precision@10_abs',
            'precision@5.0_pct',
            'precision@5_abs',
            'recall@10.0_pct',
            'recall@10_abs',
            'recall@5.0_pct',
            'recall@5_abs',
        ]


def test_generate_binary_at_x():
    input_list = [0.9, 0.8, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.6]

    # bug can arise when the same value spans both sides of threshold
    assert generate_binary_at_x(input_list, 50, 'percentile') == \
        [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]

    assert generate_binary_at_x(input_list, 2) == \
        [1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
