"""Real loopback HTTP/WebSocket exchanges with explicit HA/Docker test doubles.

These exercise our adapter boundary; they do not count as a real HA startup test.
"""
from __future__ import annotations
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import aiohttp
from aiohttp import web
import pytest
from opiha_apps.common import read_token
from opiha_apps.server import make_server
from conftest import execute

ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture
def api(manager):
    server=make_server(manager,port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield 'http://127.0.0.1:'+str(server.server_port),read_token(manager.config)
    server.shutdown();server.server_close();thread.join()

def http(url,token=None,path='/v1/overview',payload=None,extra=None):
    headers={'Authorization':'Bearer '+token} if token else {}
    if payload is not None:headers['Content-Type']='application/json'
    headers.update(extra or {})
    request=Request(url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
    try:
        with urlopen(request,timeout=3) as response:return response.status,json.load(response)
    except HTTPError as e:return e.code,json.load(e)

def test_real_http_auth_and_overview(api):
    url,token=api
    assert http(url)[0]==401
    assert http(url,'incorrect')[0]==401
    status,body=http(url,token);assert status==200 and len(body['apps'])==5 and body['supervisor'] is False
    assert token not in json.dumps(body)

def test_browser_origin_refused_even_with_manager_token(api):
    assert http(*api,extra={'Origin':'https://example.test'})[0]==403

def test_real_http_plan_approval(api,manager):
    url,token=api
    status,plan=http(url,token,'/v1/plan',{'app':'nodered','action':'install'})
    assert status==200 and not manager.engine.calls
    assert http(url,token,'/v1/apply',{'id':plan['id'],'confirm':False})[0]==400
    assert http(url,token,'/v1/apply',{'id':plan['id'],'confirm':True})[0]==200

@pytest.mark.parametrize('route',['/v1/docker','/v1/apps/../../logs','/v1/execute','/v1/overview?token=x'])
def test_no_arbitrary_control_routes(api,route):
    assert http(*api,path=route)[0]==404

def test_privileged_options_blocked_at_http_boundary(api):
    assert http(*api,path='/v1/plan',payload={'app':'nodered','action':'install','options':{'privileged':True}})[0]==400

@pytest.fixture
def component(monkeypatch):
    # Minimal host API contracts verified against HA 2026.9.3; NOT a Home Assistant runtime.
    modules={}
    def mod(name):
        m=types.ModuleType(name);modules[name]=m;monkeypatch.setitem(sys.modules,name,m);return m
    vol=mod('voluptuous')
    vol.Schema=lambda *a,**kw:lambda value:value
    vol.Optional=lambda value,**kw:value;vol.Required=lambda value,**kw:value
    vol.Any=lambda *args:args;vol.In=lambda values:values;vol.ALLOW_EXTRA=object()
    ha=mod('homeassistant');ha.__path__=[]
    components=mod('homeassistant.components');components.__path__=[]
    httpmod=mod('homeassistant.components.http');httpmod.HomeAssistantView=object;httpmod.__path__=[]
    auth=mod('homeassistant.components.http.auth');auth.async_user_not_allowed_do_auth=lambda h,u,r:False
    panel=mod('homeassistant.components.panel_custom')
    async def register(*args,**kw):pass
    panel.async_register_panel=register
    ws=mod('homeassistant.components.websocket_api');ws.websocket_command=lambda _:lambda f:f;ws.async_response=lambda f:f
    ws.async_register_command=lambda *_:None
    components.panel_custom=panel;components.websocket_api=ws
    const=mod('homeassistant.const');const.EVENT_HOMEASSISTANT_STOP='stop'
    core=mod('homeassistant.core');core.HomeAssistant=object
    path=ROOT/'homeassistant/custom_components/opiha_apps'
    spec=importlib.util.spec_from_file_location('tested_opiha_component',path/'__init__.py',submodule_search_locations=[str(path)])
    module=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,spec.name,module);spec.loader.exec_module(module)
    yield module
    for name in list(sys.modules):
        if name.startswith('tested_opiha_component.'):sys.modules.pop(name,None)

class Connection:
    def __init__(self,admin=True):self.user=types.SimpleNamespace(is_admin=admin,is_active=True);self.result=None;self.error=None
    def send_error(self,*args):self.error=args
    def send_result(self,*args):self.result=args

class FakeManagerClient:
    def __init__(self):self.calls=[]
    async def request(self,*args):self.calls.append(args);return {'ok':True}

def test_ha_ws_admin_boundary(component):
    client=FakeManagerClient();hass=types.SimpleNamespace(data={'opiha_apps':{'client':client}});conn=Connection(False)
    asyncio.run(component.ws_request(hass,conn,{'id':1,'operation':'overview','data':{}}))
    assert conn.error[1]=='unauthorized' and not client.calls

@pytest.mark.parametrize('operation,data',[('overview',{'x':1}),('apply',{'plan_id':'wrong','confirm':True}),('logs',{'app':'../../bad'}),('credentials',{'confirm':False})])
def test_ha_ws_rejects_invalid_boundaries(component,operation,data):
    client=FakeManagerClient();hass=types.SimpleNamespace(data={'opiha_apps':{'client':client}});conn=Connection()
    asyncio.run(component.ws_request(hass,conn,{'id':1,'operation':operation,'data':data}))
    assert conn.error and not client.calls

@pytest.mark.parametrize('operation,data,path',[('apply',{'id':'plan','confirm':True},'/v1/apply'),('credentials',{'confirm':True},'/v1/apps/mosquitto/credentials'),('job',{'id':'job-1'},'/v1/jobs/job-1')])
def test_ha_ws_matches_manager_contract(component,operation,data,path):
    client=FakeManagerClient();hass=types.SimpleNamespace(data={'opiha_apps':{'client':client}});conn=Connection()
    asyncio.run(component.ws_request(hass,conn,{'id':1,'operation':operation,'data':data}))
    assert conn.result and client.calls[0][1]==path

def test_client_real_loopback_and_closed_redirects(component,api):
    async def scenario():
        client=component.Client({'url':api[0],'token':api[1]})
        try:
            assert (await client.request('GET','/v1/overview'))['supervisor'] is False
            with pytest.raises(component.NativeError):await client.request('GET','/v1/../../private')
        finally:await client.close()
    asyncio.run(scenario())

@pytest.mark.parametrize('tail',['../config','%2e%2e/config','%252e%252e/config','/absolute','folder\\file','a/%2e/b','%00'])
def test_ingress_path_guards(component,tail):
    from tested_opiha_component.ingress import safe_tail
    with pytest.raises(web.HTTPException):safe_tail(tail)

@pytest.mark.parametrize('location',['https://evil.example/','//evil.example/','../api/config','/x/../../api','http://user@127.0.0.1:1880/','/ok\r\nX: y'])
def test_ingress_redirect_guards(component,location):
    from tested_opiha_component.ingress import rewrite_location
    with pytest.raises(web.HTTPException):rewrite_location(location,'/api/opiha_apps/ingress/nodered/',1880)

def test_real_ingress_cookie_http_and_websocket(component):
    async def scenario():
        from tested_opiha_component.ingress import Ingress,SessionView,PREFIX
        user=types.SimpleNamespace(id='admin-test',is_admin=True,is_active=True)
        refresh=types.SimpleNamespace(user=user)
        hass=types.SimpleNamespace(auth=types.SimpleNamespace(async_get_refresh_token=lambda value:refresh if value=='test-refresh' else None))
        seen=[]
        async def backend(request):
            seen.append((request.path,dict(request.headers)))
            if request.headers.get('Upgrade','').lower()=='websocket':
                ws=web.WebSocketResponse();await ws.prepare(request)
                async for m in ws:
                    if m.type==aiohttp.WSMsgType.TEXT:await ws.send_str('echo:'+m.data)
                return ws
            response=web.json_response({'path':request.path,'query':dict(request.query)})
            response.set_cookie('backend_session','synthetic',httponly=True)
            return response
        upstream=web.Application();upstream.router.add_route('*','/{tail:.*}',backend)
        br=web.AppRunner(upstream);await br.setup();site=web.TCPSite(br,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
        class Descriptor:
            async def request(self,method,path,body=None):
                slug=path.split('/')[3];return {'app':slug,'port':port,'prefix':PREFIX+slug+'/'}
        ingress=Ingress(hass,Descriptor());view=SessionView(ingress)
        async def mint(request):
            if request.headers.get('Authorization')=='Bearer SYNTHETIC_HA_TOKEN':
                request['hass_user']=user;request['hass_refresh_token_id']='test-refresh'
            return await view.post(request)
        async def proxy(request):return await ingress.proxy(request,request.match_info['app'],request.match_info['tail'])
        app=web.Application();app.router.add_post('/api/opiha_apps/session',mint);app.router.add_route('*',PREFIX+'{app}/{tail:.*}',proxy)
        ar=web.AppRunner(app);await ar.setup();site2=web.TCPSite(ar,'127.0.0.1',0);await site2.start();base='http://127.0.0.1:'+str(site2._server.sockets[0].getsockname()[1])
        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client:
                async with client.get(base+PREFIX+'nodered/') as res:assert res.status==401
                async with client.post(base+'/api/opiha_apps/session',json={'app':'nodered'}) as res:assert res.status==403
                async with client.post(base+'/api/opiha_apps/session',json={'app':'nodered'},headers={'Authorization':'Bearer SYNTHETIC_HA_TOKEN'}) as res:
                    assert res.status==200
                    cookie=res.headers['Set-Cookie'];assert 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
                async with client.get(base+PREFIX+'nodered/status?x=%23value',headers={'Authorization':'Bearer DO_NOT_FORWARD'}) as res:
                    assert res.status==200
                    result=await res.json();assert result['path']==PREFIX+'nodered/status' and result['query']['x']=='#value'
                assert 'Authorization' not in seen[-1][1] and 'opiha_auth' not in seen[-1][1].get('Cookie','')
                async with client.post(base+PREFIX+'nodered/action',json={},headers={'Origin':'https://evil.example'}) as res:assert res.status==403
                async with client.ws_connect(base+PREFIX+'nodered/ws',origin=base) as ws:
                    await ws.send_str('hello');response=await ws.receive(timeout=3);assert response.data=='echo:hello'
                async with client.post(base+'/api/opiha_apps/session',json={'app':'esphome'},headers={'Authorization':'Bearer SYNTHETIC_HA_TOKEN'}) as res:assert res.status==200
                async with client.get(base+PREFIX+'esphome/test') as res:assert (await res.json())['path']=='/test'
                assert seen[-1][1]['X-Ingress-Path']==PREFIX+'esphome'
                user.is_admin=False
                async with client.get(base+PREFIX+'nodered/') as res:assert res.status==401
        finally:
            await ingress.close();await ar.cleanup();await br.cleanup()
    asyncio.run(scenario())
