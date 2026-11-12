"""Ordinary browser, HTTP, Java and Gradle consumers of native Dart output."""
import functools, hashlib, html.parser, http.server, json, pathlib, shutil
import select, subprocess, sys, tempfile, threading, urllib.error, urllib.request, zipfile
from xml.etree import ElementTree as ET
Path=pathlib.Path
spec=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);out.mkdir()
def sha(data):return hashlib.sha256(data).hexdigest()
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
class DOM(html.parser.HTMLParser):
    def __init__(self):super().__init__();self.answer=False;self.value='';self.color=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id')=='answer':self.answer=True;self.color=attrs.get('data-color')
    def handle_data(self,data):
        if self.answer:self.value+=data
    def handle_endtag(self,tag):
        if tag=='p':self.answer=False
def serve(root):
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    return server,thread
def browser_url(url,value,expect_script=True):
    with tempfile.TemporaryDirectory(prefix='browser-profile-') as profile:
        result=subprocess.run([spec['chromium'],'--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-background-networking','--no-first-run','--disable-extensions','--user-data-dir='+profile,'--virtual-time-budget=3000','--dump-dom',url],capture_output=True,text=True,timeout=45)
    assert result.returncode==0,(result.stdout,result.stderr)
    dom=DOM();dom.feed(result.stdout)
    if expect_script:assert dom.value==str(value) and dom.color=='rgb(42, 43, 44)',(dom.value,dom.color,result.stdout,result.stderr)
    else:assert dom.value=='pending',(dom.value,result.stderr)
    return {'value':dom.value,'css':dom.color}
def browser(root,value,expect_script=True):
    server,thread=serve(root)
    try:return browser_url('http://127.0.0.1:'+str(server.server_port)+'/index.html',value,expect_script)
    finally:server.shutdown();server.server_close();thread.join()
def jar_browser(jar,prefix,manifest,value):
    server=subprocess.Popen(['java','ResourceServer',str(jar),prefix,str(manifest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert select.select([server.stdout],[],[],20)[0], 'Java HTTP server did not start'
        port=int(server.stdout.readline().strip())
        return browser_url('http://127.0.0.1:'+str(port)+'/index.html',value)
    finally:
        server.terminate();server.wait(timeout=10)
        error=server.stderr.read();assert not error,error
def java(jar,manifest,prefix):
    result=subprocess.run(['java','ResourceConsumer',str(jar),str(manifest),prefix],capture_output=True,text=True,timeout=30)
    assert result.returncode==0 and not result.stderr,result
    return result.stdout
def resolve(repository,index):
    poms=list(repository.rglob('*.pom'));assert len(poms)==1
    pom=ET.parse(poms[0]).getroot();ns={'m':'http://maven.apache.org/POM/4.0.0'}
    group,artifact,version=[pom.find('m:'+k,ns).text for k in ['groupId','artifactId','version']]
    coordinate=':'.join([group,artifact,version]);project=out/('gradle-'+str(index));project.mkdir()
    report=project/'resolved.txt'
    (project/'config.json').write_text(json.dumps(dict(repository=str(repository),coordinate=coordinate,report=str(report))))
    (project/'settings.gradle').write_text("rootProject.name='ordinary-dart-webjar-consumer'\n")
    (project/'build.gradle').write_text('''def selected = new groovy.json.JsonSlurper().parse(file('config.json'))
repositories { maven { url=uri(selected.repository); metadataSources { mavenPom(); artifact() } } }
configurations { assets }
dependencies { assets(selected.coordinate) }
tasks.register('resolveAssets') { doLast { new File(selected.report).text=configurations.assets.singleFile.canonicalPath } }
''')
    subprocess.run(['gradle','--offline','--no-daemon','--console=plain','resolveAssets'],cwd=project,check=True,timeout=180)
    resolved=Path(report.read_text());assert sha(resolved.read_bytes())==sha(poms[0].with_suffix('.jar').read_bytes())
    return resolved,coordinate,artifact
subprocess.run(['javac',str(Path(__file__).with_name('ResourceConsumer.java')),str(Path(__file__).with_name('ResourceServer.java')),'-d','.'],check=True)
rows=[]
for index,item in enumerate(spec['versions']):
    native=Path(item['artifact']);web=Path(item['web']);files=web/'files'
    model=json.loads((Path(item['proof'])/'model.json').read_text());expected={p:r['sha256'] for p,r in model['files'].items()}
    runtime=[name for name,record in model['files'].items() if 'owner' in record]
    assert set(expected)==({'main.wasm','main.mjs','main.support.js','index.html','style.css'} if model['target']=='wasm' else {'main.js','main.js_1.part.js','index.html','style.css'})
    for root in [native,files]:
        assert {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}==set(expected)
        assert all(sha((root/p).read_bytes())==checksum for p,checksum in expected.items())
    direct=browser(native,item['value']);projected=browser(files,item['value'])
    server,thread=serve(files)
    try:
        for name,checksum in expected.items():
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/'+name,timeout=10) as response:assert response.status==200 and sha(response.read())==checksum
        for forbidden in ['private.txt','proof/model.json','compiler-version.txt','main.js.map']:
            try:urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/'+forbidden,timeout=10)
            except urllib.error.HTTPError as e:assert e.code==404
            else:raise AssertionError('exposed private/compiler file: '+forbidden)
    finally:server.shutdown();server.server_close();thread.join()
    manifest=out/('resources-'+str(index)+'.tsv');manifest.write_text(''.join(p+'\t'+checksum+'\n' for p,checksum in sorted(expected.items())))
    java_resources=java(web/'resources.jar',manifest,'')
    jar,coordinate,artifact=resolve(Path(item['maven']),index)
    prefix='META-INF/resources/webjars/'+artifact+'/1.0.0/'
    extracted=out/('extracted-'+str(index));extracted.mkdir()
    with zipfile.ZipFile(jar) as archive:
        for name,checksum in expected.items():
            data=archive.read(prefix+name);assert sha(data)==checksum
            target=extracted/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        assert not any('private.txt' in p or '/proof/' in p for p in archive.namelist())
    java_webjar=java(jar,manifest,prefix);resolved_browser=jar_browser(jar,prefix,manifest,item['value'])
    (out/('java-'+str(index)+'.txt')).write_text(java_resources+java_webjar)
    rows.append(dict(value=item['value'],target=model['target'],coordinate=coordinate,files=expected,runtime=runtime,native=direct,web=projected,webjar=resolved_browser,webjarSha256=sha(jar.read_bytes()),compiler=model['compilerVersion'],sdk=model['sdk']))
assert rows[0]['coordinate']!=rows[1]['coordinate'],'same declared WebJar version must retain changed producer identity'
for name in (['main.wasm','main.mjs'] if rows[0]['target']=='wasm' else rows[0]['runtime']):
    missing=out/('missing-'+name);shutil.copytree(spec['versions'][0]['artifact'],missing)
    for p in [missing,*missing.rglob('*')]:p.chmod(0o755 if p.is_dir() else 0o644)
    (missing/name).unlink();assert browser(missing,42,False)['value']=='pending'
replacement=out/'compiled-replacement';shutil.copytree(spec['versions'][0]['artifact'],replacement)
for p in [replacement,*replacement.rglob('*')]:p.chmod(0o755 if p.is_dir() else 0o644)
for name in rows[1]['runtime']:shutil.copyfile(Path(spec['versions'][1]['artifact'])/name,replacement/name)
assert browser(replacement,43)['value']=='43'
assert any(sha((replacement/name).read_bytes())!=rows[0]['files'][name] for name in rows[0]['runtime'])
(out/'proof.json').write_text(json.dumps(dict(versions=rows,controls={'missingScript':'ordinary browser remains pending','genuineCompiledReplacement':'43 executes, original 42-byte identity rejected','privateAndCompilerFiles':'HTTP404 and absent from both JAR formats'}),sort_keys=True,indent=2)+'\n')
print('Native Dart browser / HTTP / Java resource JAR / ordinary Gradle WebJar consumers and controls passed')
