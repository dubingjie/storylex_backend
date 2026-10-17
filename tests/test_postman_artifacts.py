import importlib.util
import json
import re
import unittest
from pathlib import Path


class PostmanArtifacts(unittest.TestCase):
    def test_collection_covers_actual_routes_and_environment_has_no_credentials(self):
        spec=importlib.util.spec_from_file_location('postman_generator','scripts/generate_postman.py')
        generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
        collection=json.loads(Path('postman/StoryLex.postman_collection.json').read_text())
        inventory=generator.routes()
        def normalize(path):
            path=path.replace('{{base_url}}','').split('?')[0]
            path=re.sub(r'<(?:int:)?(\w+)>',r'{\1}',path)
            return re.sub(r'\{\{(\w+)\}\}',r'{\1}',path)
        expected={(r['method'],normalize(r['path'])) for r in inventory}
        actual={(item['request']['method'],normalize(item['request']['url'])) for folder in collection['item'] for item in folder['item']}
        self.assertEqual(actual,expected)
        self.assertEqual(len(actual),46)
        env=json.loads(Path('postman/StoryLex.local.postman_environment.json').read_text())
        values={v['key']:v['value'] for v in env['values']}
        for key in ('token','password','username'):
            self.assertEqual(values[key],'')
        self.assertEqual(values['enable_ai'],'false')
        self.assertEqual(values['enable_register'],'false')
        self.assertEqual(values['enable_txt'],'false')

    def test_json_request_templates_and_events_are_present(self):
        collection=json.loads(Path('postman/StoryLex.postman_collection.json').read_text())
        for folder in collection['item']:
            for item in folder['item']:
                self.assertEqual({e['listen'] for e in item['event']},{'test','prerequest'})
                body=item['request'].get('body',{})
                if body.get('mode')=='raw':
                    # 模板中的数字和数组占位符不是JSON字符串；脚本运行后才替换为实值。
                    template=re.sub(r'(?<!")\{\{[a-z_]+\}\}', '0',body['raw'])
                    self.assertIsInstance(json.loads(template),dict,item['name'])
                    script='\n'.join(item['event'][0]['script']['exec'])
                    self.assertIn('pm.request.body.update',script)
