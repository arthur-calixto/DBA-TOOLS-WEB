import unittest
from unittest.mock import MagicMock, patch
from app import db
from app.db import oracle, sqlserver
from app.db.limits import QueryResultLimitExceeded
from app.config import settings
from synthetic import CREDENTIALS


class DriverTests(unittest.TestCase):
    def connection(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [('ID',), ('VALOR',)]
        cursor.fetchmany.return_value = [(1, 'sintético'), (2, None)]
        return connection, cursor

    def test_bound_parameters_fetch_limit_and_timeouts(self):
        for module, params in [(oracle, {'id': 1}), (sqlserver, (1,))]:
            connection, cursor = self.connection()
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection):
                result = module.run_query(CREDENTIALS, 'SELECT synthetic', params)
            self.assertEqual(result, [{'ID': 1, 'VALOR': 'sintético'}, {'ID': 2, 'VALOR': None}])
            cursor.execute.assert_called_once_with('SELECT synthetic', params)
            cursor.fetchmany.assert_called_once_with(settings.db_max_rows + 1)
            cursor.fetchall.assert_not_called()
            if module is oracle:
                self.assertEqual(connection.call_timeout, settings.db_query_timeout_seconds * 1000)
                connection.__exit__.assert_called_once()
            else:
                self.assertEqual(connection.timeout, settings.db_query_timeout_seconds)
                connection.close.assert_called_once()

    def test_empty_results_and_failure_cleanup(self):
        for module in [oracle, sqlserver]:
            connection, cursor = self.connection()
            cursor.fetchmany.return_value = []
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection):
                self.assertEqual(module.run_query(CREDENTIALS, 'SELECT synthetic'), [])
                cursor.execute.side_effect = RuntimeError('synthetic')
                with self.assertRaises(RuntimeError):
                    module.run_query(CREDENTIALS, 'SELECT synthetic')
            if module is sqlserver:
                self.assertEqual(connection.close.call_count, 2)
            else:
                self.assertEqual(connection.__exit__.call_count, 2)

    def test_excess_results_fail_instead_of_truncating(self):
        for module in [oracle, sqlserver]:
            connection, cursor = self.connection()
            with self.subTest(driver=module.__name__), patch.object(settings, 'db_max_rows', 1), patch.object(module, 'get_connection', return_value=connection):
                with self.assertRaises(QueryResultLimitExceeded):
                    module.run_query(CREDENTIALS, 'SELECT synthetic')

    def test_oracle_dsn_and_connect_timeout(self):
        with patch.object(oracle.oracledb, 'makedsn', return_value='synthetic_dsn') as dsn, patch.object(oracle.oracledb, 'connect') as connect:
            oracle.get_connection(CREDENTIALS)
        dsn.assert_called_once_with('db.invalid', 1521, service_name='synthetic', sid=None)
        self.assertEqual(connect.call_args.kwargs['tcp_connect_timeout'], settings.db_connect_timeout_seconds)
        self.assertEqual(connect.call_args.kwargs['password'], 'SYNTHETIC_SECRET')

    def test_sqlserver_connection_values_are_escaped(self):
        credentials = dict(CREDENTIALS, password='a};TrustServerCertificate=no;{b', database='db;test')
        with patch.object(sqlserver.pyodbc, 'connect') as connect:
            sqlserver.get_connection(credentials)
        self.assertIn('PWD={a}};TrustServerCertificate=no;{b};', connect.call_args.args[0])
        self.assertIn('DATABASE={db;test};', connect.call_args.args[0])
        self.assertEqual(connect.call_args.kwargs['timeout'], settings.db_connect_timeout_seconds)

    def test_dispatch_both_drivers_and_reject_unknown(self):
        for dialect in ['oracle', 'sqlserver']:
            with self.subTest(dialect=dialect), patch.object(getattr(db, dialect), 'run_query', return_value=[]) as run:
                credentials = dict(CREDENTIALS, db_type=dialect)
                self.assertEqual(db.run_query(credentials, 'SELECT synthetic', (1,)), [])
                run.assert_called_once_with(credentials, 'SELECT synthetic', (1,))
        with self.assertRaises(ValueError):
            db.run_query({'db_type': 'unknown'}, 'SELECT synthetic')

    def test_exact_row_limit_is_accepted(self):
        for module in [oracle, sqlserver]:
            connection, cursor = self.connection()
            with self.subTest(driver=module.__name__), patch.object(settings, 'db_max_rows', 2), patch.object(module, 'get_connection', return_value=connection):
                self.assertEqual(len(module.run_query(CREDENTIALS, 'SELECT synthetic')), 2)

    def contract_connection(self, module):
        """Oracle fecha cursor no __exit__; pyodbc o invalida ao fechar conexão."""
        connection = MagicMock()
        cursor = MagicMock()
        events = []
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        cursor.__enter__.return_value = cursor
        cursor.description = [('ID',)]
        cursor.fetchmany.return_value = [(1,)]
        connection.close.side_effect = lambda: events.append('connection.close')
        cursor.close.side_effect = lambda: events.append('cursor.close')

        def connection_exit(*args):
            events.append('connection.__exit__')
            connection.close()
            return False

        def cursor_exit(*args):
            events.append('cursor.__exit__')
            if module is oracle:
                cursor.close()
            return False

        connection.__exit__.side_effect = connection_exit
        cursor.__exit__.side_effect = cursor_exit
        return connection, cursor, events

    def driver_error(self, module, timeout=False):
        if module is oracle:
            error_class = module.oracledb.OperationalError if timeout else module.oracledb.DatabaseError
            return error_class('DPY-4024: synthetic' if timeout else 'ORA-00000: synthetic')
        error_class = module.pyodbc.OperationalError if timeout else module.pyodbc.Error
        return error_class('HYT00' if timeout else 'HY000', 'synthetic')

    def assert_cleanup(self, module, connection, cursor, events, opened):
        connection.close.assert_called_once_with()
        if module is oracle:
            connection.__exit__.assert_called_once()
        else:
            # closing() chama close(), não Connection.__exit__ do pyodbc.
            connection.__exit__.assert_not_called()
        if opened:
            cursor.__exit__.assert_called_once()
            self.assertLess(events.index('cursor.__exit__'), events.index('connection.close'))
            if module is oracle:
                cursor.close.assert_called_once_with()
            else:
                # Cursor.__exit__ do pyodbc não chama Cursor.close(). O fechamento
                # da conexão invalida o cursor e libera seus recursos ODBC.
                cursor.close.assert_not_called()
        else:
            cursor.__enter__.assert_not_called()
            cursor.__exit__.assert_not_called()
            cursor.close.assert_not_called()

    def test_fetchmany_timeout_cleanup(self):
        for module in [oracle, sqlserver]:
            connection, cursor, events = self.contract_connection(module)
            error = self.driver_error(module, timeout=True)
            cursor.fetchmany.side_effect = error
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection):
                with self.assertRaises(type(error)) as caught:
                    module.run_query(CREDENTIALS, 'SELECT synthetic')
                self.assertIs(caught.exception, error)
                self.assertIs(cursor.__exit__.call_args.args[1], error)
                self.assert_cleanup(module, connection, cursor, events, opened=True)

    def test_fetchmany_error_cleanup(self):
        for module in [oracle, sqlserver]:
            connection, cursor, events = self.contract_connection(module)
            error = self.driver_error(module)
            cursor.fetchmany.side_effect = error
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection):
                with self.assertRaises(type(error)):
                    module.run_query(CREDENTIALS, 'SELECT synthetic')
                self.assert_cleanup(module, connection, cursor, events, opened=True)

    def test_timeout_configuration_failure_cleanup(self):
        from unittest.mock import PropertyMock
        for module in [oracle, sqlserver]:
            connection, cursor, events = self.contract_connection(module)
            error = self.driver_error(module)
            attribute = 'call_timeout' if module is oracle else 'timeout'
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection), patch.object(type(connection), attribute, new_callable=PropertyMock, create=True, side_effect=error):
                with self.assertRaises(type(error)):
                    module.run_query(CREDENTIALS, 'SELECT synthetic')
                connection.cursor.assert_not_called()
                self.assert_cleanup(module, connection, cursor, events, opened=False)

    def test_cursor_creation_failure_cleanup(self):
        for module in [oracle, sqlserver]:
            connection, cursor, events = self.contract_connection(module)
            error = self.driver_error(module)
            connection.cursor.side_effect = error
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection):
                with self.assertRaises(type(error)):
                    module.run_query(CREDENTIALS, 'SELECT synthetic')
                self.assert_cleanup(module, connection, cursor, events, opened=False)

    def test_execute_error_cleanup(self):
        for module in [oracle, sqlserver]:
            for timeout in [False, True]:
                connection, cursor, events = self.contract_connection(module)
                error = self.driver_error(module, timeout=timeout)
                cursor.execute.side_effect = error
                with self.subTest(driver=module.__name__, timeout=timeout), patch.object(module, 'get_connection', return_value=connection):
                    with self.assertRaises(type(error)):
                        module.run_query(CREDENTIALS, 'SELECT synthetic')
                    cursor.fetchmany.assert_not_called()
                    self.assert_cleanup(module, connection, cursor, events, opened=True)

    def test_contract_cleanup_on_success(self):
        for module in [oracle, sqlserver]:
            connection, cursor, events = self.contract_connection(module)
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection):
                self.assertEqual(module.run_query(CREDENTIALS, 'SELECT synthetic'), [{'ID': 1}])
                self.assert_cleanup(module, connection, cursor, events, opened=True)
                self.assertEqual(cursor.__exit__.call_args.args, (None, None, None))

    def test_connection_closes_if_cursor_exit_fails(self):
        for module in [oracle, sqlserver]:
            connection, cursor, events = self.contract_connection(module)
            error = self.driver_error(module)
            cursor.__exit__.side_effect = error
            with self.subTest(driver=module.__name__), patch.object(module, 'get_connection', return_value=connection):
                with self.assertRaises(type(error)):
                    module.run_query(CREDENTIALS, 'SELECT synthetic')
                connection.close.assert_called_once_with()
