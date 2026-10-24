"""Exercise actual profile-card JavaScript with source and portrait distinctions."""
from pathlib import Path
import shutil
import subprocess
import unittest


class TeacherCardsUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for isolated UI checks.')
    def test_actual_renderer_keeps_text_profiles_without_placeholder_faces(self):
        root = Path(__file__).resolve().parents[1]
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(process.argv[1],'utf8');
new vm.Script(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
const code=html.slice(html.indexOf('function renderTeacherCards('),html.indexOf('function renderTurn('));
class Element {
 constructor(tag){this.tagName=tag;this.children=[];this.events={};this.textContent=''}
 append(...items){for(const item of items){item.parent=this;this.children.push(item)}}
 addEventListener(key,fn){this.events[key]=fn}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this)}
 set innerHTML(value){throw Error('Unsafe HTML used')}
}
function node(tag,text,cls){const el=new Element(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
const ctx={node,document:{createElement:tag=>new Element(tag)},URL};vm.createContext(ctx);vm.runInContext(code,ctx);
const render=cards=>ctx.renderTeacherCards(cards);
const all=(n,tag)=>n?[...(n.tagName===tag?[n]:[]),...n.children.flatMap(x=>all(x,tag))]:[];
const words=n=>n?[n.textContent,...n.children.map(words)].join(' '):'';
const base={name:'Source Teacher',role:'Source Role',department:'Source Department',captured_utc:'2026-01-02T00:00:00Z',source_url:'https://nmct.edu.mn/departments/example'};
const photo={...base,image_url:'/api/teacher-media/teacher-'+'a'.repeat(24)};
const text={...base,name:'Text Teacher',portrait_available:false,image_status:'source_placeholder_excluded',image_url:null};
let list=render([photo,{...photo,name:'Other'},text,{...text,name:'Fourth'}]);
assert.equal(all(list,'article').length,4);assert.equal(all(list,'img').length,2);
assert.deepEqual(all(list,'h3').map(n=>n.textContent),['Source Teacher','Other','Text Teacher','Fourth']);
assert(words(list).includes('жишээ зураг'));assert(words(list).includes('2026-01-02'));
assert.equal(all(list,'a').length,4);assert(all(list,'a').every(n=>n.rel==='noopener noreferrer'));
for(const card of [{...text,image_status:undefined},{...text,image_url:undefined},
 {...text,image_url:'https://attacker.example/a.png'},{...photo,image_url:'https://attacker.example/a.png'},
 {...photo,image_url:'/api/teacher-media/../private.txt'},{...photo,portrait_available:false},
 {...text,source_url:'https://nmct.edu.mn.attacker.example/'},
 {...text,source_url:'https://user:secret@nmct.edu.mn/'},{...text,source_url:'javascript:alert(1)'}])assert.equal(render([card]),null);
list=render([{...text,name:'<img src=x onerror=alert(1)>'}]);
assert.equal(all(list,'h3')[0].textContent,'<img src=x onerror=alert(1)>');assert.equal(all(list,'img').length,0);
list=render([photo]);const image=all(list,'img')[0];assert.equal(image.loading,'lazy');
assert.equal(image.referrerPolicy,'no-referrer');image.events.error();assert.equal(all(list,'img').length,0);
assert(words(list).includes('ачаалж чадсангүй'));
list=render(Array(8).fill(text));assert.equal(all(list,'article').length,6);
assert.equal(render(null),null);assert.equal(render([]),null);
'''
        result = subprocess.run([shutil.which('node'), '-e', script, str(root/'demo/index.html')],
            cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
