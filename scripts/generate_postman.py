"""从实际Flask装饰器生成Postman集合和路由清单，不导入应用或连接数据库。"""
import ast
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def routes():
    result=[]
    for file in [ROOT/'app.py',*sorted((ROOT/'routes').glob('*.py'))]:
        tree=ast.parse(file.read_text())
        prefix=''
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='Blueprint':
                prefix=next((ast.literal_eval(k.value) for k in node.keywords if k.arg=='url_prefix'),'')
        for node in ast.walk(tree):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            for dec in node.decorator_list:
                if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.attr=='route':
                    path=prefix+ast.literal_eval(dec.args[0])
                    methods=next((ast.literal_eval(k.value) for k in dec.keywords if k.arg=='methods'),['GET'])
                    for method in methods:
                        result.append({'method':method,'path':path,'function':node.name,'file':str(file.relative_to(ROOT)),'line':node.lineno})
    return result


def raw(data):
    text=json.dumps(data,ensure_ascii=False,indent=2)
    for key in ['word_id','learn_word_id','review_word_id','pause_word_id','mastered_word_id','learn_word_ids','favorite_word_ids','ai_word_ids','progress_version','draft_version']:
        text=text.replace('"{{'+key+'}}"','{{'+key+'}}')
    return text


BODIES={
 '/api/auth/register':{'username':'{{username}}','password':'{{password}}'},
 '/api/auth/login':{'username':'{{username}}','password':'{{password}}'},
 '/api/user/book':{'book_id':'{{switch_book_id}}'},
 '/api/user/favorites/batch-delete':{'word_ids':'{{favorite_word_ids}}'},
 '/api/user/favorites/practice':{'word_ids':'{{favorite_word_ids}}','request_id':'favorite-create-{{run_id}}','mode':'mixed'},
 '/api/words/target/update':{'task_type':'new','target_count':10},
 '/api/words/learn/answer':{'group_id':'{{learn_group_id}}','word_id':'{{learn_word_id}}','question_id':'{{learn_question_id}}','request_id':'learn-answer-{{learn_question_id}}','selected_key':'{{selected_key}}','is_show_answer':False},
 '/api/words/learn/group/complete':{'group_id':'{{learn_group_id}}'},
 '/api/words/review/answer':{'group_id':'{{review_group_id}}','word_id':'{{review_word_id}}','question_id':'{{review_question_id}}','request_id':'review-answer-{{review_question_id}}','selected_key':'{{selected_key}}','is_show_answer':False},
 '/api/words/review/complete':{'group_id':'{{review_group_id}}'},
 '/api/words/master':{'word_id':'{{word_id}}'},
 '/api/words/favorite/toggle':{'word_id':'{{word_id}}','source_type':'story'},
 '/api/words/learn/group/practice':{'word_ids':'{{learn_word_ids}}','request_id':'learn-practice-{{run_id}}','mode':'mixed'},
 '/api/words/practice/<session_id>/submit':{'request_id':'independent-submit-{{run_id}}','answers':'{{independent_answers}}'},
 '/api/words/review/pause':{'word_id':'{{pause_word_id}}','request_id':'pause-{{run_id}}'},
 '/api/words/review/resume':{'word_id':'{{pause_word_id}}','request_id':'resume-{{run_id}}'},
 '/api/words/master/reset':{'word_id':'{{mastered_word_id}}','request_id':'reset-{{run_id}}'},
 '/api/stories/complete':{'story_id':'{{story_id}}'},
 '/api/stories/<int:story_id>/favorite':{'is_favorited':True},
 '/api/stories/<int:story_id>/progress':{'progress':35.5,'position':5,'version':'{{progress_version}}'},
 '/api/stories/<int:story_id>/practice/submit':{'session_id':'{{reading_session_id}}','request_id':'reading-submit-{{run_id}}','answers':'{{reading_answers}}'},
 '/api/ai/generate-story':{'word_ids':'{{ai_word_ids}}','request_id':'ai-generate-{{run_id}}','story_type':'日常故事'},
 '/api/ai/drafts/<draft_id>':{'version':'{{draft_version}}','title':'{{draft_title}}','processed_content':'{{draft_content}}'},
 '/api/ai/drafts/<draft_id>/save':{'version':'{{draft_version}}','request_id':'draft-save-{{run_id}}'},
}
BODIES['/api/stories/generate']=BODIES['/api/ai/generate-story']
TITLES={
 'health_check':'服务健康检查','register':'注册测试账号','login':'登录并保存Token','get_current_user':'查询当前身份',
 'get_learn_group':'获取或恢复新学题组','check_learn_answer':'新学逐题判定','complete_learn_group':'新学组通关结算',
 'get_review_group':'获取正式复习题组','answer_review_word':'正式复习答题','complete_review_group':'查询复习组结果',
 'master_word':'标记已掌握','toggle_favorite':'单词收藏切换（再次发送会反转）','get_favorite_words':'旧路径收藏列表',
 'update_daily_target':'修改每日目标','get_group_practice_questions':'小结自主练习出题','get_book_words_list':'查询词书单词',
 'get_dashboard_summary':'首页任务与继续阅读','get_independent_practice':'查询自主练习','submit_independent_practice':'提交自主练习',
 'pause_review_word':'暂停正式复习','resume_review_word':'恢复暂停词','reset_mastered_word':'重置已掌握词','get_paused_review_words':'已暂停词列表',
 'get_story_list':'文库分页及筛选','get_story_detail':'文章详情','complete_story':'手动完读打卡','generate_story':'旧路径AI预览',
 'get_story_vocabulary':'本章词表','get_story_practice':'阅读练习出题','submit_story_practice':'提交阅读练习','story_reading_progress':'阅读进度',
 'set_story_favorite':'设置文章收藏（改false取消）','get_dashboard':'旧结构首页统计','get_personal_stats':'个人累计统计',
 'get_books':'词书列表','switch_book':'切换主修词书','get_favorites':'收藏夹列表','batch_delete_favorites':'批量取消收藏',
 'create_favorite_practice':'收藏夹自主练习出题','generate_story_preview':'AI生成预览（需主动启用）','story_draft':'草稿查询或编辑',
 'save_story_draft':'确认保存草稿','import_txt_preview':'TXT上传预览（需选择本地文件）',
}
QUERIES={
 '/api/stories/list':'?scope=all&category=all&keyword=&page=1&page_size=10',
 '/api/words/book/list':'?filter=all&page=1&page_size=20',
 '/api/user/favorites':'?page=1&page_size=20',
 '/api/words/favorite/list':'?page=1&page_size=20',
 '/api/words/review/paused':'?page=1&page_size=20',
}
CAPTURE=r'''
function put(k,v){if(v!==undefined&&v!==null)pm.environment.set(k,typeof v==='object'?JSON.stringify(v):String(v));}
if(b.code===200){
 const d=b.data||{};
 if(d.token)put('token',d.token);
 if(d.current_book_id)put('current_book_id',d.current_book_id);
 if(d.story_id)put('story_id',d.story_id);
 if(d.list&&d.list.length&&pm.request.url.toString().includes('/stories/list'))put('story_id',d.list[0].story_id);
 if(Object.prototype.hasOwnProperty.call(d,'group_id')&&!d.group_id){const k=pm.request.url.toString().includes('/review/')?'review':'learn';put(k+'_group_id','');put(k+'_total',0);put(k+'_passed_count',0);}
 if(pm.request.url.toString().includes('/learn/answer')){put('learn_passed_count',d.passed_count);put('learn_total',d.total);}
 if(d.draft_id){put('draft_id',d.draft_id);put('draft_version',d.version);put('draft_title',d.title);put('draft_content',d.processed_content);}
 if(d.version!==undefined&&d.progress!==undefined)put('progress_version',d.version);
 if(d.list&&pm.request.url.toString().includes('/favorites'))put('favorite_word_ids',d.list.slice(0,2).map(w=>w.word_id));
 if(d.list&&pm.request.url.toString().includes('/book/list')){
  if(d.list.length)put('word_id',d.list[0].word_id);
  put('ai_word_ids',d.list.slice(0,2).map(w=>w.word_id));
  const mastered=d.list.find(w=>w.is_mastered);if(mastered)put('mastered_word_id',mastered.word_id);
 }
 if(d.group_id){
  const kind=pm.request.url.toString().includes('/review/')?'review':'learn';
  put(kind+'_group_id',d.group_id);put(kind+'_passed_count',d.passed_count);put(kind+'_total',d.total);
  const w=(d.words||[]).find(w=>!w.passed);
  if(w){put(kind+'_word_id',w.word_id);put(kind+'_question_id',w.question_id);if(kind==='review')put('pause_word_id',w.word_id);}
 }
 if(d.retry_question){put('learn_word_id',d.retry_question.word_id);put('learn_question_id',d.retry_question.question_id);}
 if(d.summary_list)put('learn_word_ids',d.summary_list.map(w=>w.word_id));
 if(d.questions&&d.session_id){
  const answers=d.questions.map(q=>({question_id:q.question_id,word_id:q.word_id,selected_key:'A'}));
  if(pm.request.url.toString().includes('/stories/')){put('reading_session_id',d.session_id);put('reading_answers',answers);}
  else{put('session_id',d.session_id);put('independent_answers',answers);}
 }
}
'''


def build():
    folder_names={'routes/auth.py':'01 注册登录','routes/user.py':'02 用户词书与收藏夹','routes/words.py':'03 新学复习与自主练习','routes/stories.py':'04 文库与阅读','routes/ai.py':'05 AI与TXT草稿','app.py':'00 健康检查'}
    groups={name:[] for name in sorted(folder_names.values())}
    records=routes()
    for route in records:
        path,method=route['path'],route['method']
        converted=re.sub(r'<(?:int:)?(\w+)>',r'{{\1}}',path)
        url='{{base_url}}'+converted+QUERIES.get(path,'')
        request={'method':method,'header':[],'url':url,'description':f"实际路由：{method} {path}\n来源：{route['file']}:{route['line']}\n修改请求会操作当前账号数据，请使用测试账号。缺少上下文时预脚本会跳过；见postman/README.md。"}
        if path.startswith('/api/auth/') and path!='/api/auth/me':request['auth']={'type':'noauth'}
        if path=='/api/health':request['auth']={'type':'noauth'}
        if method in ('POST','PUT') and path in BODIES:
            text=raw(BODIES[path])
            for key in ['story_id','independent_answers','reading_answers']:
                text=text.replace('"{{'+key+'}}"','{{'+key+'}}')
            request['body']={'mode':'raw','raw':text,'options':{'raw':{'language':'json'}}}
            request['header']=[{'key':'Content-Type','value':'application/json'}]
        if path=='/api/ai/import-txt':
            request['body']={'mode':'formdata','formdata':[
                {'key':'file','type':'file','src':'samples/import_demo.txt'},
                {'key':'target_book_id','type':'text','value':'{{current_book_id}}'},
                {'key':'request_id','type':'text','value':'txt-import-{{run_id}}'},
                {'key':'title','type':'text','value':'TXT验收预览'}]}
        prereq=[]
        def guard(condition,message):prereq.append(f"if({condition}){{console.warn({json.dumps(message,ensure_ascii=False)});pm.execution.skipRequest();}}")
        if request.get('auth',{}).get('type')!='noauth':guard("!pm.variables.get('token')",'请先登录并保存token')
        for key in ('story_id','draft_id','session_id'):
            if '{{'+key+'}}' in url:guard(f"!pm.variables.get('{key}')",f'请先取得{key}')
        text=json.dumps(request.get('body',{}),ensure_ascii=False)
        for key in ['word_id','learn_word_id','review_word_id','pause_word_id','mastered_word_id','learn_group_id','review_group_id','learn_question_id','review_question_id']:
            if '{{'+key+'}}' in text:guard(f"!pm.variables.get('{key}')",f'请先选择有效的{key}')
        for key in ['learn_word_ids','favorite_word_ids','ai_word_ids','independent_answers','reading_answers']:
            if '{{'+key+'}}' in text:guard(f"!pm.variables.get('{key}')||pm.variables.get('{key}')==='[]'",f'请先取得非空{key}')
        if path in ('/api/auth/register','/api/auth/login'):
            guard("!pm.variables.get('username')||!pm.variables.get('password')",'请填写测试账号username/password')
        if path=='/api/auth/register':guard("pm.variables.get('enable_register')!=='true'",'注册默认关闭，需enable_register=true')
        if path in ('/api/ai/generate-story','/api/stories/generate'):guard("pm.variables.get('enable_ai')!=='true'",'真实模型调用默认关闭，需enable_ai=true')
        if path=='/api/ai/import-txt':guard("pm.variables.get('enable_txt')!=='true'",'请选择本地TXT并设置enable_txt=true')
        if path=='/api/words/learn/group/complete':guard("Number(pm.variables.get('learn_passed_count')||0)<Number(pm.variables.get('learn_total')||1)",'尚未全部通关，先完成逐题答题再结算')
        if path=='/api/user/book':guard("!pm.variables.get('switch_book_id')",'请先设置switch_book_id')
        if request.get('body',{}).get('mode')=='raw':
            template=json.dumps(BODIES[path],ensure_ascii=False)
            numeric=['word_id','learn_word_id','review_word_id','pause_word_id','mastered_word_id','progress_version','draft_version','story_id']
            arrays=['learn_word_ids','favorite_word_ids','ai_word_ids','independent_answers','reading_answers']
            prereq += ['const bodyTemplate='+template+';',
                'const numericKeys='+json.dumps(numeric)+';const arrayKeys='+json.dumps(arrays)+';',
                "function resolveBody(v){if(typeof v==='string'){const m=v.match(/^\\{\\{([a-z_]+)\\}\\}$/);if(m){const k=m[1],s=pm.variables.get(k);if(numericKeys.includes(k))return Number(s);if(arrayKeys.includes(k))return JSON.parse(s||'[]');return s===undefined?'':s;}return pm.variables.replaceIn(v);}if(Array.isArray(v))return v.map(resolveBody);if(v&&typeof v==='object'){const out={};Object.keys(v).forEach(k=>out[k]=resolveBody(v[k]));return out;}return v;}",
                'pm.request.body.update(JSON.stringify(resolveBody(bodyTemplate)));']
        test="let b=pm.response.json();\npm.test('业务code为200',()=>pm.expect(b.code,b.msg).to.eql(200));\n"+CAPTURE
        if path in ('/api/ai/generate-story','/api/stories/generate'):
            test+="\npm.test('生成任务可用',()=>pm.expect(['ready','generating','saved']).to.include(b.data.status));"
        groups[folder_names[route['file']]].append({'name':TITLES.get(route['function'],route['function'])+' ['+method+']',
            'request':request,'event':[{'listen':'prerequest','script':{'type':'text/javascript','exec':prereq}},
                                     {'listen':'test','script':{'type':'text/javascript','exec':test.splitlines()}}]})
    collection={'info':{'name':'StoryLex 后端验收与前端对接','schema':'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
                       'description':'按真实路由生成，覆盖全部方法/路径。用于手动联调，不是一键自动通关脚本。模型/注册/TXT默认关闭，使用独立测试账号。'},
                'auth':{'type':'bearer','bearer':[{'key':'token','value':'{{token}}','type':'string'}]},
                'item':[{'name':name,'item':items} for name,items in groups.items()]}
    variables={'base_url':'http://192.168.30.97:5000','username':'','password':'','token':'','run_id':'manual-001',
               'enable_register':'false','enable_ai':'false','enable_txt':'false','current_book_id':'','switch_book_id':'',
               'story_id':'','word_id':'','pause_word_id':'','mastered_word_id':'','draft_id':'','draft_version':'1',
               'draft_title':'','draft_content':'','progress_version':'0','selected_key':'A','learn_group_id':'',
               'learn_word_id':'','learn_question_id':'','learn_passed_count':'0','learn_total':'0','learn_word_ids':'[]',
               'review_group_id':'','review_word_id':'','review_question_id':'','favorite_word_ids':'[]','ai_word_ids':'[]',
               'session_id':'','reading_session_id':'','independent_answers':'[]','reading_answers':'[]'}
    env={'name':'StoryLex 本地测试（不含凭证）','_postman_variable_scope':'environment',
         'values':[{'key':k,'value':v,'enabled':True,'type':'secret' if k in ('password','token') else 'default'} for k,v in variables.items()]}
    (ROOT/'postman/StoryLex.postman_collection.json').write_text(json.dumps(collection,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'postman/StoryLex.local.postman_environment.json').write_text(json.dumps(env,ensure_ascii=False,indent=2)+'\n')
    lines=['# 实际路由清单','',f'由 `scripts/generate_postman.py` 静态读取代码生成，共 {len(records)} 个方法/路径组合（包含兼容路径）。','',
           '| 方法 | 实际路径 | 处理函数 | 文件 |','|---|---|---|---|']
    lines += [f"| {r['method']} | `{r['path']}` | `{r['function']}` | [{r['file']}](../{r['file']}) |" for r in sorted(records,key=lambda r:(r['path'],r['method']))]
    (ROOT/'docs/实际路由清单.md').write_text('\n'.join(lines)+'\n')
    print(f'Generated {len(records)} requests and route inventory')


if __name__=='__main__':build()
