from collate.collate import Aggregate, Categorical
from collate.spacetime import SpacetimeAggregation
import logging


class FeatureGenerator(object):
    def __init__(self, db_engine, features_schema_name):
        self.db_engine = db_engine
        self.features_schema_name = features_schema_name
        self.categorical_cache = {}

    def _compute_choices(self, choice_query):
        if choice_query not in self.categorical_cache:
            self.categorical_cache[choice_query] = [
                row[0]
                for row
                in self.db_engine.execute(choice_query)
            ]
        return self.categorical_cache[choice_query]

    def _build_choices(self, categorical):
        if 'choices' in categorical:
            return categorical['choices']
        else:
            return self._compute_choices(categorical['choice_query'])

    def _build_categoricals(self, categorical_config):
        return [
            Categorical(
                col=categorical['column'],
                choices=self._build_choices(categorical),
                function=categorical['metrics']
            )
            for categorical in categorical_config
        ]

    def _aggregation(self, aggregation_config, feature_dates):
        aggregates = [
            Aggregate(aggregate['quantity'], aggregate['metrics'])
            for aggregate in aggregation_config.get('aggregates', [])
        ]
        logging.info('Found %s quantity aggregates', len(aggregates))
        categoricals = self._build_categoricals(
            aggregation_config.get('categoricals', [])
        )
        logging.info('Found %s categorical aggregates', len(categoricals))
        return SpacetimeAggregation(
            aggregates + categoricals,
            from_obj=aggregation_config['from_obj'],
            intervals=aggregation_config['intervals'],
            groups=aggregation_config['groups'],
            dates=feature_dates,
            date_column=aggregation_config['knowledge_date_column'],
            output_date_column='as_of_date',
            schema=self.features_schema_name,
            prefix=aggregation_config['prefix']
        )

    def aggregations(self, feature_aggregation_config, feature_dates):
        """Creates collate.SpacetimeAggregations from the given arguments

        Args:
            feature_aggregation_config (list) all values, except for feature
                date, necessary to instantiate a collate.SpacetimeAggregation
            feature_dates (list) dates to generate features as of

        Returns: (list) collate.SpacetimeAggregations
        """
        return [
            self._aggregation(aggregation_config, feature_dates)
            for aggregation_config in feature_aggregation_config
        ]

    def generate_all_table_tasks(self, feature_aggregation_config, feature_dates):
        """Generates SQL commands for creating, populating, and indexing
        feature group tables

        Args:
            feature_aggregation_config (list) all values, except for feature
                date, necessary to instantiate a collate.SpacetimeAggregation
            feature_dates (list) dates to generate features as of

        Returns: (dict) keys are group table names,
            values are a dict of kwargs suitable for self.create_group_table
        """
        logging.debug('---------------------')
        logging.debug('---------FEATURE GENERATION------------')
        logging.debug('---------------------')
        table_tasks = {}
        aggregations = self.aggregations(feature_aggregation_config, feature_dates)
        self._explain_selects(aggregations)
        for aggregation in aggregations:
            table_tasks.update(self._generate_table_tasks_for(aggregation))
        logging.info('Created %s tables', len(table_tasks.keys()))
        return table_tasks

    def create_all_tables(self, feature_aggregation_config, feature_dates):
        """Creates all feature tables.

        Args:
            feature_aggregation_config (list) all values, except for feature
                date, necessary to instantiate a collate.SpacetimeAggregation
            feature_dates (list) dates to generate features as of

        Returns: (list) table names
        """
        table_tasks = self.generate_all_table_tasks(
            feature_aggregation_config,
            feature_dates
        )
        for table_name, kwargs in table_tasks.items():
            self.create_group_table(**kwargs)
        return table_tasks.keys()

    def _explain_selects(self, aggregations):
        conn = self.db_engine.connect()
        for aggregation in aggregations:
            for selectlist in aggregation.get_selects().values():
                for select in selectlist:
                    result = [row for row in conn.execute('explain ' + str(select))]
                    logging.debug(str(select))
                    logging.debug(result)

    def _clean_table_name(self, table_name):
        # remove the schema and quotes from the name
        return table_name.split('.')[1].replace('"', "")

    def create_group_table(self, group_table, drop, create, inserts, index):
        """Executes the SQL commands for creating, populating, and indexing
        a feature group table

        Args:
            group_table (str) name of the table
            drop (str) SQL to drop the table
            create (collate.sql.CreateTableAs) SQL to create the table
            inserts (collate.sql.InsertFromSelect) SQL commands to insert data
                from a select statement
            index (str) SQL to index the table

        Returns: nothing
        """
        logging.info('Processing group table %s', group_table)
        conn = self.db_engine.connect()
        trans = conn.begin()
        conn.execute(drop)
        conn.execute(create)
        for insert in inserts:
            conn.execute(insert)
        conn.execute(index)
        trans.commit()
        logging.info('Done processing %s', group_table)

    def _generate_table_tasks_for(self, aggregation):
        """Generates SQL commands for creating, populating, and indexing
        each feature group table in the given aggregation

        Args:
            aggregation (collate.SpacetimeAggregation)

        Returns: (dict) keys are group table names,
            values are a dict of kwargs suitable for self.create_group_table
        """
        create_schema = aggregation.get_create_schema()
        creates = aggregation.get_creates()
        drops = aggregation.get_drops()
        indexes = aggregation.get_indexes()
        inserts = aggregation.get_inserts()

        if create_schema is not None:
            self.db_engine.execute(create_schema)

        table_tasks = {}
        for group in aggregation.groups:
            group_table = self._clean_table_name(
                aggregation.get_table_name(group=group)
            )
            table_tasks[group_table] = {
                'group_table': group_table,
                'drop': drops[group],
                'create': creates[group],
                'inserts': inserts[group],
                'index': indexes[group]
            }

        return table_tasks
