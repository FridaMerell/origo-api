"""Inbound API integrations: validation, generation and the generated client run against a fake ``requests``.

Nothing here needs a database or network. The generated client is written to a temp directory and imported
with stand-ins for ``requests`` and Django's cache, so the code that ships to a project is what gets exercised.
"""

import importlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from flux.services.scaffold import ScaffoldError, generate_files
from flux.services.scaffold.integration import (
    clean_auth,
    clean_base_url,
    clean_operation,
    extract_items,
    py_name,
    resolve_path,
)
from flux.tests.test_scaffold import make_spec

STATION = {'id': 's-1', 'properties': {'name': 'Abisko', 'elevation': 388.5}, 'region_id': 7, 'meta': {'deleted': False}}
LIST_SAMPLE = {'data': {'items': [STATION, {**STATION, 'id': 's-2', 'meta': {'deleted': True}}]}}
ENTITY = {
    'fields': {
        'external_id': {'type': 'string', 'nullable': False},
        'name': {'type': 'string', 'nullable': False},
        'elevation': {'type': 'float', 'nullable': True},
        'active': {'type': 'bool', 'nullable': False},
    },
    'relations': {'region': 'fk', 'tags': 'm2m'},
}


def operation(**overrides):
    data = {
        'name': 'list_stations', 'method': 'GET', 'path': '/stations',
        'params': [{'name': 'regionCode', 'in': 'query', 'type': 'string', 'required': True}],
        'items_path': 'data.items', 'pagination': 'offset',
        'pagination_config': {'limit_param': 'limit', 'offset_param': 'offset', 'page_size': 2},
        'filters': [{'path': 'meta.deleted', 'op': 'eq', 'value': False}],
        'mappings': [
            {'path': 'id', 'field': 'external_id'}, {'path': 'properties.name', 'field': 'name'},
            {'path': 'properties.elevation', 'field': 'elevation'}, {'path': 'region_id', 'field': 'region'},
        ],
        'key_field': 'external_id', 'sync': True, 'sync_interval_minutes': 60, 'sample_response': LIST_SAMPLE,
    }
    data.update(overrides)
    return data


def rejects(test, data, entity=ENTITY, fragment=None):
    with test.assertRaises(ValueError) as caught:
        clean_operation(data, entity)
    if fragment:
        test.assertIn(fragment, str(caught.exception))


class AuthAndUrlTests(unittest.TestCase):
    def test_base_url_must_be_https(self):
        self.assertEqual(clean_base_url('https://api.example.test/v2'), 'https://api.example.test/v2')
        for bad in ('http://api.example.test', 'ftp://x', 'https://a b', 'https://x"y'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_base_url(bad)

    def test_each_auth_type_requires_its_settings(self):
        cases = {
            'api_key_header': {'auth_name': 'X-Key', 'auth_env_var': 'SVC_KEY'},
            'api_key_query': {'auth_name': 'key', 'auth_env_var': 'SVC_KEY'},
            'bearer': {'auth_env_var': 'SVC_TOKEN'},
            'basic': {'auth_env_var': 'SVC_USER', 'auth_secret_env_var': 'SVC_PASS'},
            'oauth_client': {'auth_env_var': 'ID', 'auth_secret_env_var': 'SECRET', 'oauth_token_url': 'https://a.test/t'},
        }
        for auth_type, settings in cases.items():
            with self.subTest(auth_type=auth_type):
                self.assertEqual(clean_auth({'auth_type': auth_type, **settings})['auth_type'], auth_type)
                with self.assertRaises(ValueError):
                    clean_auth({'auth_type': auth_type})

    def test_env_var_names_and_unknown_auth_types_are_rejected(self):
        for bad in ({'auth_type': 'magic'}, {'auth_type': 'bearer', 'auth_env_var': 'lower_case'}, {'auth_type': 'bearer', 'auth_env_var': 'A B'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_auth(bad)
        self.assertEqual(clean_auth({})['auth_type'], 'none')


class PathHelperTests(unittest.TestCase):
    def test_resolve_path_follows_dicts_and_list_indexes(self):
        data = {'a': {'b': [{'c': 5}]}}

        self.assertEqual(resolve_path(data, 'a.b.0.c'), (True, 5))
        self.assertEqual(resolve_path(data, 'a.x'), (False, None))
        self.assertEqual(resolve_path(data, 'a.b.3'), (False, None))
        self.assertEqual(resolve_path({'a': None}, 'a'), (True, None))

    def test_extract_items(self):
        self.assertEqual(extract_items([1, 2], ''), [1, 2])
        self.assertEqual(extract_items({'a': 1}, ''), [{'a': 1}])
        self.assertEqual(extract_items({'d': [1]}, 'd'), [1])
        with self.assertRaises(ValueError):
            extract_items({'d': [1]}, 'missing')
        with self.assertRaises(ValueError):
            extract_items({'d': 5}, 'd')

    def test_python_argument_names(self):
        self.assertEqual(py_name('pageSize'), 'page_size')
        self.assertEqual(py_name('X-Trace-Id'), 'x_trace_id')
        self.assertEqual(py_name('regionCode'), 'region_code')


class OperationValidationTests(unittest.TestCase):
    def test_a_valid_operation_is_returned_cleaned(self):
        cleaned = clean_operation(operation(), ENTITY)

        self.assertEqual(cleaned['pagination_config']['max_pages'], 100)
        self.assertEqual(cleaned['params'][0]['required'], True)
        self.assertEqual(cleaned['name'], 'list_stations')

    def test_name_method_and_path(self):
        for change, fragment in (
            ({'name': 'List Stations'}, 'identifier'), ({'name': 'class'}, 'identifier'),
            ({'method': 'DELETE'}, 'method'), ({'path': 'stations'}, 'path'),
            ({'path': '/stations?x=1'}, 'path'), ({'path': '/a/{b'}, 'placeholders'),
        ):
            with self.subTest(change=change):
                rejects(self, operation(**change), fragment=fragment)

    def test_path_placeholders_must_match_path_params(self):
        rejects(self, operation(path='/stations/{station_id}'), fragment='placeholders')
        rejects(self, operation(params=[{'name': 'station_id', 'in': 'path'}]), fragment='placeholders')

    def test_param_rules(self):
        rejects(self, operation(params=[{'name': 'q', 'in': 'body'}]), fragment='POST')
        rejects(self, operation(params=[{'name': 'use_cache'}]), fragment='Python argument')
        rejects(self, operation(params=[{'name': 'from', 'in': 'query'}]), fragment='Python argument')
        rejects(self, operation(params=[{'name': 'a'}, {'name': 'A'}]), fragment='Duplicate')
        rejects(self, operation(params=[{'name': 'a', 'required': True, 'default': 'x'}]), fragment='default')
        rejects(self, operation(params=[{'name': 'a', 'type': 'int', 'default': 'x'}]), fragment='default')
        rejects(self, operation(params=[{'name': 'a', 'type': 'blob'}]), fragment='type')

    def test_pagination_config_is_required_and_checked(self):
        rejects(self, operation(pagination_config={'limit_param': 'limit'}), fragment='offset_param')
        rejects(self, operation(pagination='cursor', pagination_config={'cursor_param': 'after'}), fragment='next_cursor_path')
        rejects(self, operation(pagination_config={'limit_param': 'regionCode', 'offset_param': 'o', 'page_size': 2}), fragment='also declared')
        rejects(self, operation(pagination='sideways'), fragment='pagination')
        self.assertEqual(clean_operation(operation(pagination='none', pagination_config={'junk': 1}), ENTITY)['pagination_config'], {})

    def test_a_paginated_operation_needs_a_list_in_the_sample(self):
        rejects(self, operation(items_path='data', sample_response={'data': {'items': []}}), fragment='list')

    def test_mappings_need_an_entity_and_a_real_sample(self):
        rejects(self, operation(), entity=None, fragment='entity')
        rejects(self, operation(sample_response=None), fragment='sample_response is required')
        rejects(self, operation(sample_response={'data': {'items': []}}), fragment='no items')

    def test_mapping_paths_must_exist_in_the_sample(self):
        rejects(self, operation(mappings=[{'path': 'properties.nope', 'field': 'name'}], key_field='name'), fragment='does not exist')

    def test_mapping_types_must_match_the_entity(self):
        rejects(self, operation(mappings=[{'path': 'properties.name', 'field': 'elevation'}], key_field='elevation'), fragment='float')
        rejects(self, operation(mappings=[{'path': 'properties.elevation', 'field': 'name'}], key_field='name'), fragment='string')
        rejects(self, operation(mappings=[{'path': 'properties.name', 'field': 'active'}], key_field='active'), fragment='bool')

    def test_null_values_only_fit_nullable_fields(self):
        sample = {'data': {'items': [{'id': 's', 'properties': {'name': None, 'elevation': None}}]}}
        good = operation(sample_response=sample, filters=[], mappings=[{'path': 'id', 'field': 'external_id'}, {'path': 'properties.elevation', 'field': 'elevation'}])
        self.assertEqual(clean_operation(good, ENTITY)['name'], 'list_stations')
        bad = operation(sample_response=sample, filters=[], mappings=[{'path': 'id', 'field': 'external_id'}, {'path': 'properties.name', 'field': 'name'}])
        rejects(self, bad, fragment='null')

    def test_mapped_fields_must_exist_and_not_be_many_to_many(self):
        rejects(self, operation(mappings=[{'path': 'id', 'field': 'ghost'}], key_field='ghost'), fragment='not a field')
        rejects(self, operation(mappings=[{'path': 'id', 'field': 'tags'}], key_field='tags'), fragment='Many-to-many')
        rejects(self, operation(mappings=[{'path': 'id', 'field': 'name'}, {'path': 'id', 'field': 'name'}]), fragment='more than once')

    def test_relations_must_map_to_a_key_value(self):
        sample = {'data': {'items': [{'id': 's', 'region_id': {'nested': True}}]}}
        rejects(self, operation(sample_response=sample, filters=[], mappings=[{'path': 'id', 'field': 'external_id'}, {'path': 'region_id', 'field': 'region'}]), fragment='primary key')

    def test_key_field_rules(self):
        rejects(self, operation(key_field='not_mapped'), fragment='mapped')
        rejects(self, operation(key_field='region'), fragment='plain field')

    def test_sync_needs_entity_mappings_and_key_and_interval_needs_sync(self):
        rejects(self, operation(sync=True), entity=None, fragment='entity')
        rejects(self, operation(mappings=[], key_field=''), fragment='mappings and a key_field')
        rejects(self, operation(sync=False), fragment='sync_interval_minutes needs sync')

    def test_filter_rules(self):
        rejects(self, operation(filters=[{'path': 'meta.nope', 'op': 'eq', 'value': 1}]), fragment='does not exist')
        rejects(self, operation(filters=[{'path': 'meta.deleted', 'op': 'contains', 'value': 1}]), fragment='op')
        rejects(self, operation(filters=[{'path': 'meta.deleted', 'op': 'in', 'value': 'x'}]), fragment='list')

    def test_the_sample_must_not_be_huge(self):
        huge = {'data': {'items': [{'id': 'x' * 250_000}]}}

        rejects(self, operation(sample_response=huge, filters=[], mappings=[], key_field='', sync=False, sync_interval_minutes=None), fragment='200 kB')

    def test_an_operation_without_mappings_or_sample_is_fine(self):
        cleaned = clean_operation({'name': 'ping', 'path': '/ping'}, None)

        self.assertEqual((cleaned['method'], cleaned['pagination'], cleaned['mappings']), ('GET', 'none', []))


def integration_spec(name='Weather Service', auth=None, operations=None, **extra):
    operations = operations if operations is not None else [operation()]
    cleaned = []
    for item in operations:
        entity = ENTITY if item.get('mappings') else None
        result = clean_operation(item, entity)
        result.update(entity='Station' if item.get('mappings') else None, description=item.get('description', ''))
        cleaned.append(result)
    spec = make_spec(entities=[{
        'name': 'Station', 'description': '',
        'fields': [
            {'name': 'external_id', 'type': 'string', 'nullable': False, 'unique': True, 'default': '', 'max_length': None, 'description': ''},
            {'name': 'name', 'type': 'string', 'nullable': False, 'unique': False, 'default': '', 'max_length': None, 'description': ''},
            {'name': 'elevation', 'type': 'float', 'nullable': True, 'unique': False, 'default': '', 'max_length': None, 'description': ''},
            {'name': 'active', 'type': 'bool', 'nullable': False, 'unique': False, 'default': '', 'max_length': None, 'description': ''},
        ],
        'relations': [
            {'name': 'region', 'target': 'Region', 'kind': 'fk', 'related_name': '', 'on_delete': 'cascade', 'nullable': False, 'description': ''},
        ],
    }], resources=[])
    spec['stack']['app_label'] = 'demo'
    spec['integrations'] = [{
        'name': name, 'kind': 'api', 'description': 'Station data.', 'env_vars': [],
        'base_url': 'https://api.example.test/v2', 'auth_type': 'none', 'auth_name': '', 'auth_env_var': '',
        'auth_secret_env_var': '', 'oauth_token_url': '', 'timeout_seconds': 5, 'retries': 2,
        'rate_limit_per_minute': None, 'cache_ttl_seconds': 0, 'operations': cleaned, **(auth or {}), **extra,
    }]
    return spec


class GeneratorOutputTests(unittest.TestCase):
    def files(self, spec):
        return {item['path']: item['content'] for item in generate_files(spec, 'integration')}

    def test_generates_the_expected_files(self):
        files = self.files(integration_spec())

        for path in (
            'demo/integrations/__init__.py', 'demo/integrations/weather_service.py',
            'demo/integrations/weather_service_sync.py', 'demo/management/commands/sync_weather_service.py',
            'demo/management/__init__.py', 'demo/management/commands/__init__.py', 'demo/tasks.py',
            'demo/tests/__init__.py', 'demo/tests/test_weather_service.py',
            'demo/tests/fixtures/weather_service_list_stations.json', 'docs/integrations/weather_service.md',
        ):
            self.assertIn(path, files)

    def test_no_sync_files_when_nothing_syncs(self):
        spec = integration_spec(operations=[operation(sync=False, sync_interval_minutes=None)])

        files = self.files(spec)

        self.assertNotIn('demo/integrations/weather_service_sync.py', files)
        self.assertNotIn('demo/tasks.py', files)
        self.assertNotIn('demo/management/__init__.py', files)

    def test_tasks_only_for_scheduled_operations(self):
        spec = integration_spec(operations=[operation(sync_interval_minutes=None)])

        files = self.files(spec)

        self.assertIn('demo/integrations/weather_service_sync.py', files)
        self.assertNotIn('demo/tasks.py', files)

    def test_scheduled_tasks_requeue_themselves(self):
        tasks = self.files(integration_spec())['demo/tasks.py']

        self.assertIn('@task()', tasks)
        self.assertIn('timedelta(minutes=60)', tasks)
        self.assertIn('.enqueue(**params)', tasks)

    def test_the_sync_matches_on_the_key_and_skips_incomplete_records(self):
        sync = self.files(integration_spec())['demo/integrations/weather_service_sync.py']

        self.assertIn('update_or_create(external_id=key, defaults=values)', sync)
        self.assertIn("['name', 'region_id']", sync)

    def test_every_python_file_parses(self):
        import ast

        for path, content in self.files(integration_spec()).items():
            if path.endswith('.py'):
                ast.parse(content, path)

    def test_requires_operations_and_a_base_url(self):
        with self.assertRaises(ScaffoldError):
            generate_files(make_spec(), 'integration')
        with self.assertRaises(ScaffoldError):
            generate_files(integration_spec(base_url=''), 'integration')

    def test_a_mapping_to_a_removed_field_is_reported(self):
        spec = integration_spec()
        spec['entities'][0]['fields'] = [f for f in spec['entities'][0]['fields'] if f['name'] != 'name']

        with self.assertRaisesRegex(ScaffoldError, 'no longer a field'):
            generate_files(spec, 'integration')

    def test_docs_describe_operations_and_mappings(self):
        docs = self.files(integration_spec())['docs/integrations/weather_service.md']

        self.assertIn('`list_stations()`', docs)
        self.assertIn('| `properties.name` | `name` |', docs)
        self.assertIn('every 60 min', docs)
        self.assertIn('Verify before you trust', docs)

    def test_skeleton_adds_requests_and_task_settings_only_when_needed(self):
        with_sync = {i['path']: i['content'] for i in generate_files(integration_spec(), 'skeleton')}
        plain = {i['path']: i['content'] for i in generate_files(make_spec(), 'skeleton')}

        self.assertIn('requests', with_sync['requirements.txt'])
        self.assertIn('django-tasks', with_sync['requirements.txt'])
        self.assertIn('"django_tasks_db"', with_sync['config/settings.py'])
        self.assertIn('TASKS = {', with_sync['config/settings.py'])
        self.assertNotIn('requests', plain['requirements.txt'])
        self.assertNotIn('TASKS', plain['config/settings.py'])


class GeneratedClientTests(unittest.TestCase):
    """Import the generated client with a fake ``requests`` and drive it."""

    def setUp(self):
        self.calls, self.script, self.store = [], [], {}
        test = self

        class RequestException(Exception):
            pass

        requests = types.ModuleType('requests')
        requests.request = lambda method, url, **kwargs: (test.calls.append((method, url, kwargs)), test.script.pop(0))[1]
        requests.post = lambda url, **kwargs: (test.calls.append(('TOKEN', url, kwargs)), test.script.pop(0))[1]
        requests.RequestException = RequestException
        self.RequestException = RequestException
        cache = types.ModuleType('django.core.cache')
        cache.cache = types.SimpleNamespace(get=self.store.get, set=lambda key, value, ttl: self.store.__setitem__(key, value))
        django_test = types.ModuleType('django.test')
        django_test.SimpleTestCase = unittest.TestCase
        modules = {'requests': requests, 'django.core.cache': cache, 'django.test': django_test}
        for parent in ('django', 'django.core'):
            if importlib.util.find_spec(parent) is None:
                modules[parent] = types.ModuleType(parent)
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self._forget)
        env = mock.patch.dict(os.environ, {'SVC_KEY': 'k1', 'SVC_USER': 'u', 'SVC_PASS': 'p', 'ID': 'id', 'SECRET': 's'})
        env.start()
        self.addCleanup(env.stop)

    def _forget(self):
        for name in [n for n in sys.modules if n == 'demo' or n.startswith('demo.')]:
            del sys.modules[name]
        if self.tmp in sys.path:
            sys.path.remove(self.tmp)

    def response(self, payload, status=200, headers=None):
        result = mock.Mock()
        result.status_code, result.headers, result.text = status, headers or {}, 'body'
        result.json.return_value = payload
        result.raise_for_status = lambda: None
        return result

    def load(self, spec):
        for item in generate_files(spec, 'integration'):
            target = Path(self.tmp) / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item['content'], encoding='utf-8')
        sys.path.insert(0, self.tmp)
        importlib.invalidate_caches()
        slug = spec['integrations'][0]['name'].lower().replace(' ', '_')
        return importlib.import_module(f'demo.integrations.{slug}')

    def test_offset_pagination_filters_auth_and_mapping(self):
        client = self.load(integration_spec(auth={'auth_type': 'api_key_header', 'auth_name': 'X-API-Key', 'auth_env_var': 'SVC_KEY'}))
        page2 = {'data': {'items': [{**STATION, 'id': 's-3'}]}}
        self.script[:] = [self.response(LIST_SAMPLE), self.response(page2)]

        items = client.list_stations(region_code='north', use_cache=False)

        self.assertEqual([item['id'] for item in items], ['s-1', 's-3'])
        first, second = self.calls
        self.assertEqual(first[1], 'https://api.example.test/v2/stations')
        self.assertEqual(first[2]['params'], {'regionCode': 'north', 'limit': 2, 'offset': 0})
        self.assertEqual(second[2]['params']['offset'], 2)
        self.assertEqual(first[2]['headers']['X-API-Key'], 'k1')
        self.assertEqual(
            client.map_list_stations(items[0]),
            {'external_id': 's-1', 'name': 'Abisko', 'elevation': 388.5, 'region_id': 7},
        )

    def test_cursor_pagination_stops_on_an_empty_cursor_and_applies_filters(self):
        op = operation(
            name='search', method='POST', path='/search', mappings=[], key_field='', sync=False, sync_interval_minutes=None,
            params=[{'name': 'q', 'in': 'body', 'type': 'string', 'required': True}, {'name': 'kind', 'in': 'query', 'default': 'all'}, {'name': 'X-Trace', 'in': 'header'}],
            items_path='results', pagination='cursor',
            pagination_config={'cursor_param': 'after', 'next_cursor_path': 'paging.next', 'size_param': 'size', 'page_size': 2},
            filters=[{'path': 'status', 'op': 'in', 'value': ['ok', 'new']}, {'path': 'note', 'op': 'is_null'}],
            sample_response={'results': [{'id': 1, 'status': 'ok', 'note': None}], 'paging': {'next': None}},
        )
        client = self.load(integration_spec(name='Cursor Api', operations=[op], auth={'auth_type': 'api_key_query', 'auth_name': 'key', 'auth_env_var': 'SVC_KEY'}))
        self.script[:] = [
            self.response({'results': [{'id': 1, 'status': 'ok', 'note': None}, {'id': 2, 'status': 'bad'}], 'paging': {'next': 'c2'}}),
            self.response({'results': [{'id': 3, 'status': 'new', 'note': 'x'}, {'id': 4, 'status': 'new'}], 'paging': {'next': ''}}),
        ]

        items = client.search(q='abc', x_trace='t-1', use_cache=False)

        self.assertEqual([item['id'] for item in items], [1, 4])
        first, second = self.calls
        self.assertEqual(first[0], 'POST')
        self.assertEqual((first[2]['json'], first[2]['data']), ({'q': 'abc'}, None))
        self.assertEqual(first[2]['params'], {'kind': 'all', 'size': 2, 'key': 'k1'})
        self.assertEqual(first[2]['headers'], {'X-Trace': 't-1'})
        self.assertEqual(second[2]['params']['after'], 'c2')

    def test_runaway_pagination_is_stopped_with_a_clear_error(self):
        op = operation(
            name='search', mappings=[], key_field='', sync=False, sync_interval_minutes=None, params=[], items_path='results',
            pagination='cursor', pagination_config={'cursor_param': 'after', 'next_cursor_path': 'next', 'max_pages': 3},
            filters=[], sample_response={'results': [{'id': 1}], 'next': None},
        )
        client = self.load(integration_spec(name='Endless Api', operations=[op]))
        self.script[:] = [self.response({'results': [{'id': 1}], 'next': 'again'}) for _ in range(10)]

        with self.assertRaisesRegex(client.EndlessApiAPIError, 'More than 3 pages'):
            client.search(use_cache=False)

        self.assertEqual(len(self.calls), 3)

    def test_page_pagination_basic_auth_and_form_body(self):
        op = operation(
            name='list_items', method='POST', path='/items', body_format='form', mappings=[], key_field='', sync=False,
            sync_interval_minutes=None, params=[{'name': 'tag', 'in': 'body', 'required': True}], items_path='', filters=[],
            pagination='page', pagination_config={'page_param': 'page', 'size_param': 'per_page', 'page_size': 2, 'first_page': 1},
            sample_response=[{'id': 1}],
        )
        client = self.load(integration_spec(name='Page Api', operations=[op], auth={'auth_type': 'basic', 'auth_env_var': 'SVC_USER', 'auth_secret_env_var': 'SVC_PASS'}))
        self.script[:] = [self.response([{'id': 1}, {'id': 2}]), self.response([{'id': 3}])]

        items = client.list_items(tag='t', use_cache=False)

        self.assertEqual([item['id'] for item in items], [1, 2, 3])
        first, second = self.calls
        self.assertEqual(first[2]['auth'], ('u', 'p'))
        self.assertEqual((first[2]['data'], first[2]['json']), ({'tag': 't'}, None))
        self.assertEqual(first[2]['params'], {'page': 1, 'per_page': 2})
        self.assertEqual(second[2]['params']['page'], 2)

    def test_oauth_token_is_fetched_once_and_reused(self):
        op = {'name': 'get_me', 'path': '/me', 'sample_response': {'id': 1}}
        auth = {'auth_type': 'oauth_client', 'auth_env_var': 'ID', 'auth_secret_env_var': 'SECRET', 'oauth_token_url': 'https://auth.example.test/token'}
        client = self.load(integration_spec(name='Oauth Api', operations=[op], auth=auth))
        self.script[:] = [self.response({'access_token': 'tok', 'expires_in': 3600}), self.response({'id': 1}), self.response({'id': 1})]

        client.get_me(use_cache=False)
        client.get_me(use_cache=False)

        tokens = [call for call in self.calls if call[0] == 'TOKEN']
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0][2]['data']['client_id'], 'id')
        self.assertEqual([call[2]['headers']['Authorization'] for call in self.calls if call[0] == 'GET'], ['Bearer tok', 'Bearer tok'])

    def test_bearer_auth_and_rate_limit(self):
        client = self.load(integration_spec(name='Bearer Api', operations=[{'name': 'ping', 'path': '/ping', 'sample_response': {'ok': True}}], auth={'auth_type': 'bearer', 'auth_env_var': 'SVC_KEY'}))
        client.RATE_LIMIT_PER_MINUTE = 60
        self.script[:] = [self.response({'ok': True}), self.response({'ok': True})]

        with mock.patch.object(client.time, 'sleep') as sleep:
            client.ping(use_cache=False)
            client.ping(use_cache=False)

        self.assertEqual(self.calls[0][2]['headers']['Authorization'], 'Bearer k1')
        self.assertGreaterEqual(sleep.call_count, 1)

    def test_path_parameters_are_url_quoted(self):
        op = {'name': 'get_station', 'path': '/stations/{station_id}', 'params': [{'name': 'station_id', 'in': 'path'}], 'items_path': 'data', 'sample_response': {'data': STATION}}
        client = self.load(integration_spec(name='Path Api', operations=[op]))
        self.script[:] = [self.response({'data': STATION})]

        result = client.get_station(station_id='a/b c', use_cache=False)

        self.assertEqual(self.calls[0][1], 'https://api.example.test/v2/stations/a%2Fb%20c')
        self.assertEqual(result, [STATION])

    def test_results_are_cached_per_arguments(self):
        client = self.load(integration_spec(name='Cached Api', cache_ttl_seconds=60, operations=[{'name': 'get_thing', 'path': '/thing', 'params': [{'name': 'id', 'type': 'int'}], 'sample_response': {'a': 1}}]))
        self.script[:] = [self.response({'a': 1}), self.response({'a': 2})]

        first = client.get_thing(id=1)
        again = client.get_thing(id=1)
        other = client.get_thing(id=2)

        self.assertEqual(first, again)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(other, [{'a': 2}])

    def test_retries_then_succeeds_and_honours_retry_after(self):
        client = self.load(integration_spec(name='Retry Api', operations=[{'name': 'ping', 'path': '/ping', 'sample_response': {'ok': True}}]))
        self.script[:] = [self.response({}, 503), self.response({}, 429, {'Retry-After': '0'}), self.response({'ok': True})]

        with mock.patch.object(client.time, 'sleep') as sleep:
            result = client.ping(use_cache=False)

        self.assertEqual(result, [{'ok': True}])
        self.assertEqual((len(self.calls), sleep.call_count), (3, 2))

    def test_client_errors_and_network_failures(self):
        client = self.load(integration_spec(name='Error Api', operations=[{'name': 'ping', 'path': '/ping', 'sample_response': {'ok': True}}]))
        self.script[:] = [self.response({}, 404)]
        with self.assertRaises(client.ErrorApiAPIError):
            client.ping(use_cache=False)
        self.assertEqual(len(self.calls), 1)

        def down(*args, **kwargs):
            raise self.RequestException('down')

        with mock.patch.object(client.requests, 'request', down), mock.patch.object(client.time, 'sleep'):
            with self.assertRaisesRegex(client.ErrorApiAPIError, '3 attempts'):
                client.ping(use_cache=False)

    def test_missing_credentials_and_a_changed_response_shape(self):
        client = self.load(integration_spec(name='Guard Api', operations=[{'name': 'get_x', 'path': '/x', 'items_path': 'data', 'sample_response': {'data': {'a': 1}}}], auth={'auth_type': 'bearer', 'auth_env_var': 'SVC_KEY'}))
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(client.GuardApiConfigurationError, 'SVC_KEY'):
                client.get_x(use_cache=False)
        self.script[:] = [self.response({'unexpected': True})]
        with self.assertRaisesRegex(client.GuardApiAPIError, 'API may have changed'):
            client.get_x(use_cache=False)

    def test_the_generated_tests_pass(self):
        spec = integration_spec(auth={'auth_type': 'api_key_header', 'auth_name': 'X-API-Key', 'auth_env_var': 'SVC_KEY'})
        self.load(spec)
        suite = unittest.defaultTestLoader.discover(
            str(Path(self.tmp) / 'demo' / 'tests'), pattern='test_weather_service.py', top_level_dir=self.tmp
        )

        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)

        self.assertGreaterEqual(result.testsRun, 5)
        self.assertTrue(result.wasSuccessful(), [str(f[1]) for f in result.failures + result.errors])
