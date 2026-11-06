"""Bounded local HTML generator for large catalog-page requests.

Invoked explicitly by the agent's reviewed shell command. Reads one selected
HTML, preserves its title/product text, backs it up, and writes UTF-8 atomically.
No network, subprocess, external assets, padding comments or blank-line filling.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile


class SourcePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title=[];self.names=[];self.prices=[]
        self.in_title=False;self.in_product=False;self.product_tag=None;self.depth=0
        self.capture_tag=None;self.capture_kind=None;self.buffer=[];self.name_seen=False

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);classes=attrs.get('class','').split()
        if tag=='title':self.in_title=True
        if not self.in_product and any(name in classes for name in ('product','product-card')):
            self.in_product=True;self.product_tag=tag;self.depth=1;self.name_seen=False
        elif self.in_product and tag==self.product_tag:self.depth+=1
        if self.in_product:
            kind='price' if 'price' in classes else ('name' if tag=='h3' or tag=='p' and not self.name_seen else None)
            if kind:self.capture_tag=tag;self.capture_kind=kind;self.buffer=[]

    def handle_data(self,data):
        if self.in_title:self.title.append(data)
        if self.capture_kind:self.buffer.append(data)

    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
        if tag==self.capture_tag:
            value=' '.join(''.join(self.buffer).split())
            if value:
                (self.prices if self.capture_kind=='price' else self.names).append(value)
                if self.capture_kind=='name':self.name_seen=True
            self.capture_tag=self.capture_kind=None;self.buffer=[]
        if self.in_product and tag==self.product_tag:
            self.depth-=1
            if self.depth==0:self.in_product=False


CSS={
':root':{'--cocoa':'#35221c','--caramel':'#ad6d37','--cream':'#faf5ed','--ink':'#372a25','--muted':'#786860','--line':'#e6dacb','--white':'#fffdf9','--radius':'24px','--shadow':'0 20px 70px #35221c12','font-family':"'Segoe UI',Arial,sans-serif",'color':'var(--ink)','background':'var(--cream)'},
'*':{'box-sizing':'border-box'},'html':{'scroll-behavior':'smooth','scroll-padding-top':'100px'},'body':{'margin':'0','line-height':'1.65'},
'a':{'color':'inherit','text-decoration':'none'},'button,input':{'font':'inherit'},'button':{'cursor':'pointer'},'button:disabled':{'opacity':'.5','cursor':'default'},
'button:focus-visible,a:focus-visible,input:focus-visible':{'outline':'3px solid #bb8955','outline-offset':'5px'},
'.container':{'width':'min(1160px,calc(100% - 44px))','margin-inline':'auto'},
'.skip-link':{'position':'fixed','top':'-80px','left':'20px','padding':'12px 20px','background':'white','z-index':'30'},'.skip-link:focus':{'top':'12px'},
'.topline':{'padding':'8px','text-align':'center','font-size':'12px','letter-spacing':'.12em','background':'var(--cocoa)','color':'#e8d5bc'},
'.header':{'position':'sticky','top':'0','z-index':'10','background':'#faf5edf0','backdrop-filter':'blur(16px)','border-bottom':'1px solid var(--line)'},
'.navigation':{'display':'flex','align-items':'center','justify-content':'space-between','min-height':'84px','gap':'24px'},
'.brand':{'font-weight':'750','font-size':'24px','letter-spacing':'-.04em'},'.brand small':{'display':'block','font-size':'9px','letter-spacing':'.28em','font-weight':'500','text-transform':'uppercase'},
'.navlinks':{'display':'flex','gap':'24px','align-items':'center','font-size':'14px'},'.navlinks a:hover':{'color':'var(--caramel)'},
'.cart-toggle':{'border':'1px solid var(--line)','border-radius':'40px','background':'transparent','padding':'10px 18px','color':'var(--cocoa)'},
'.menu-toggle':{'display':'none','background':'transparent','border':'1px solid var(--line)','border-radius':'12px','padding':'9px 13px'},
'.hero':{'display':'grid','grid-template-columns':'1.05fr 1fr','align-items':'center','gap':'50px','padding-block':'80px'},
'.eyebrow':{'font-size':'11px','letter-spacing':'.2em','text-transform':'uppercase','font-weight':'700','color':'var(--caramel)'},
'h1,h2,h3,p':{'margin-top':'0'},'h1':{'font-size':'clamp(42px,5.3vw,76px)','line-height':'1.06','letter-spacing':'-.055em','margin-block':'16px 25px'},
'h2':{'font-size':'clamp(28px,3.4vw,44px)','line-height':'1.15','letter-spacing':'-.04em'},'h3':{'line-height':'1.3'},
'.lead':{'font-size':'18px','max-width':'490px','color':'var(--muted)'},'.actions':{'display':'flex','gap':'12px','flex-wrap':'wrap','margin-top':'30px'},
'.button':{'display':'inline-flex','align-items':'center','justify-content':'center','border':'1px solid var(--cocoa)','border-radius':'40px','padding':'13px 25px','background':'var(--cocoa)','color':'white','font-weight':'600','transition':'transform .2s,background .2s'},
'.button:hover':{'transform':'translateY(-2px)','background':'#56372b'},'.button.secondary':{'background':'transparent','color':'var(--cocoa)','border-color':'var(--line)'},
'.hero-art':{'position':'relative','aspect-ratio':'1','display':'grid','place-items':'center','background':'radial-gradient(circle at 40% 35%,#e8c8a3,#b77b4b 75%)','border-radius':'48% 48% 42% 42%','overflow':'hidden','box-shadow':'var(--shadow)'},
'.hero-art:before':{'content':"''",'position':'absolute','inset':'14%','border':'1px solid #ffffff50','border-radius':'50%'},
'.chocolate':{'width':'58%','aspect-ratio':'1.1','background':'linear-gradient(135deg,#754b37,#281712)','border-radius':'34%','transform':'rotate(-18deg)','box-shadow':'20px 35px 35px #3b201a55,inset 3px 3px 8px #a6795d'},
'.chocolate:after':{'content':"''",'position':'absolute','inset':'12%','border':'2px solid #bf94733a','border-radius':'30%'},
'.art-label':{'position':'absolute','bottom':'24px','left':'30px','color':'white','font-size':'12px','letter-spacing':'.12em'},
'.features':{'display':'grid','grid-template-columns':'repeat(3,1fr)','border-block':'1px solid var(--line)','padding-block':'22px','gap':'25px'},
'.feature':{'display':'flex','gap':'13px','align-items':'center'},'.feature span':{'display':'grid','place-items':'center','width':'38px','height':'38px','background':'#efe3d3','border-radius':'50%','color':'var(--caramel)'},
'.feature strong':{'display':'block','font-size':'13px'},'.feature small':{'color':'var(--muted)','font-size':'12px'},
'.section':{'padding-block':'75px'},'.section-heading':{'display':'flex','align-items':'end','justify-content':'space-between','gap':'25px','margin-bottom':'30px'},
'.section-heading p':{'color':'var(--muted)','max-width':'430px','margin-bottom':'0'},
'.search':{'width':'100%','padding':'14px 20px','border':'1px solid var(--line)','border-radius':'15px','background':'var(--white)','margin-bottom':'25px'},
'.catalog':{'display':'grid','grid-template-columns':'repeat(auto-fit,minmax(240px,1fr))','gap':'24px'},
'.product-card':{'background':'var(--white)','border':'1px solid var(--line)','border-radius':'var(--radius)','overflow':'hidden','box-shadow':'0 8px 40px #35221c06','transition':'transform .2s,box-shadow .2s'},
'.product-card:hover':{'transform':'translateY(-5px)','box-shadow':'var(--shadow)'},'.product-visual':{'position':'relative','height':'230px','display':'grid','place-items':'center','background':'linear-gradient(145deg,#f0e4d2,#e4cbae)'},
'.product-visual .chocolate':{'width':'110px','box-shadow':'13px 22px 22px #3b201a25'},'.product-body':{'padding':'24px'},'.product-body h3':{'font-size':'20px','margin-bottom':'10px'},
'.product-description':{'font-size':'14px','color':'var(--muted)'},'.product-footer':{'display':'flex','justify-content':'space-between','align-items':'center','gap':'15px'},
'.price':{'font-size':'16px','font-weight':'700'},'.add-button':{'border':'0','border-radius':'50%','background':'var(--cocoa)','color':'white','width':'40px','height':'40px','font-size':'22px'},
'.empty':{'padding':'25px','color':'var(--muted)','text-align':'center'},'.story':{'display':'grid','grid-template-columns':'1fr 1fr','gap':'55px','align-items':'center','background':'#eee1d0','padding':'45px','border-radius':'var(--radius)'},
'.story-quote':{'font-size':'clamp(25px,3vw,40px)','font-weight':'600','line-height':'1.25','letter-spacing':'-.03em'},'.story p':{'color':'var(--muted)'},
'.occasion-grid':{'display':'grid','grid-template-columns':'repeat(3,1fr)','gap':'22px'},'.occasion':{'padding':'28px','border':'1px solid var(--line)','border-radius':'20px','background':'var(--white)'},
'.occasion b':{'display':'block','font-size':'22px','margin-bottom':'12px'},'.occasion p':{'color':'var(--muted)','font-size':'14px','margin-bottom':'0'},
'.faq':{'max-width':'820px','margin-inline':'auto'},'details':{'border-bottom':'1px solid var(--line)','padding-block':'18px'},'summary':{'cursor':'pointer','font-weight':'650'},'details p':{'color':'var(--muted)','padding-top':'14px','margin-bottom':'0'},
'.footer':{'background':'var(--cocoa)','color':'#eadac9','padding-block':'45px'},'.footer-grid':{'display':'grid','grid-template-columns':'1fr 1fr','gap':'40px'},'.footer a':{'display':'block','font-size':'14px','margin-bottom':'8px'},
'.footer small':{'color':'#c3a58a'},'.cart-panel':{'position':'fixed','top':'0','right':'0','width':'min(420px,100%)','height':'100dvh','z-index':'25','background':'var(--white)','padding':'28px','box-shadow':'-20px 0 90px #35221c25','overflow-y':'auto'},
'.cart-header':{'display':'flex','justify-content':'space-between','align-items':'center','margin-bottom':'25px'},'.close-cart':{'background':'transparent','border':'0','font-size':'28px'},
'.cart-item':{'display':'flex','gap':'15px','justify-content':'space-between','padding-block':'18px','border-bottom':'1px solid var(--line)'},'.cart-item button':{'background':'transparent','border':'0','text-decoration':'underline','color':'var(--muted)'},
'.toast':{'position':'fixed','left':'50%','bottom':'24px','transform':'translateX(-50%)','padding':'12px 24px','background':'var(--cocoa)','color':'white','border-radius':'40px','box-shadow':'var(--shadow)','z-index':'40'},
'[hidden]':{'display':'none !important'},'@media(max-width:760px)':{'.hero':{'grid-template-columns':'1fr','padding-block':'45px','gap':'35px'},'.hero-art':{'max-width':'480px','width':'100%','margin-inline':'auto'},'.navlinks':{'display':'none'},'.navlinks.open':{'display':'flex','position':'absolute','top':'84px','left':'0','right':'0','padding':'25px','background':'var(--cream)','flex-direction':'column'},'.menu-toggle':{'display':'block'},'.features,.occasion-grid,.story,.footer-grid':{'grid-template-columns':'1fr'},'.story':{'padding':'28px'},'.section-heading':{'display':'block'},'.section':{'padding-block':'48px'}}
}

CSS['@media(max-width:760px)'].update({'.navigation':{'gap':'10px'},'.brand':{'font-size':'20px','max-width':'45%','line-height':'1.2','overflow-wrap':'anywhere'},'.brand small':{'font-size':'8px','letter-spacing':'.12em'},'.cart-toggle':{'padding':'8px 10px','font-size':'12px','flex-shrink':'0'},'.menu-toggle':{'padding':'8px','font-size':'12px'}})

JS='''const cart = [];
const panel = document.querySelector('.cart-panel');
const menu = document.querySelector('.menu-toggle');
const links = document.querySelector('.navlinks');
const cartList = document.querySelector('.cart-list');
const count = document.querySelector('.cart-count');
const search = document.querySelector('#search');
const toast = document.querySelector('.toast');
let toastTimer;
function notify(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 2400);
}
function renderCart() {
  cartList.replaceChildren();
  count.textContent = String(cart.length);
  if (!cart.length) {
    const empty = document.createElement('p');
    empty.textContent = 'Sua seleção está vazia. Explore os produtos.';
    cartList.append(empty);
  }
  cart.forEach((name, index) => {
    const row = document.createElement('div');
    const text = document.createElement('span');
    const remove = document.createElement('button');
    row.className = 'cart-item';
    text.textContent = name;
    remove.textContent = 'Remover';
    remove.setAttribute('aria-label', 'Remover ' + name);
    remove.addEventListener('click', () => { cart.splice(index, 1); renderCart(); });
    row.append(text, remove);
    cartList.append(row);
  });
}
menu.addEventListener('click', () => {
  const expanded = menu.getAttribute('aria-expanded') === 'true';
  menu.setAttribute('aria-expanded', String(!expanded));
  links.classList.toggle('open', !expanded);
});
links.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  links.classList.remove('open');
  menu.setAttribute('aria-expanded', 'false');
}));
document.querySelector('.cart-toggle').addEventListener('click', () => {
  panel.hidden = false;
  renderCart();
  document.querySelector('.close-cart').focus();
});
document.querySelector('.close-cart').addEventListener('click', () => {
  panel.hidden = true;
  document.querySelector('.cart-toggle').focus();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !panel.hidden) {
    panel.hidden = true;
    document.querySelector('.cart-toggle').focus();
  }
});
document.querySelectorAll('.add-button').forEach(button => button.addEventListener('click', () => {
  const name = button.closest('.product-card').querySelector('h3').textContent;
  cart.push(name);
  renderCart();
  notify(name + ' adicionado à sua seleção');
}));
search.addEventListener('input', () => {
  const query = search.value.trim().toLocaleLowerCase('pt-BR');
  let visible = 0;
  document.querySelectorAll('.product-card').forEach(card => {
    const matches = card.textContent.toLocaleLowerCase('pt-BR').includes(query);
    card.hidden = !matches;
    if (matches) { visible += 1; }
  });
  document.querySelector('.no-results').hidden = visible !== 0;
});
renderCart();'''


def render(source, lines=1000):
    parser=SourcePage();parser.feed(source)
    title=' '.join(''.join(parser.title).split()).split(' - ')[0].split(' — ')[0] or 'Catálogo de chocolates'
    names=parser.names or ['Trufas','Tabletes de chocolate']
    products=[(name,parser.prices[i] if i<len(parser.prices) else 'Consulte o catálogo') for i,name in enumerate(names[:24])]
    groups=[]
    def line(text):groups.append([text])
    def tag(name,attrs=None,text=None,close=True):
        attributes=[f'{key}="{escape(str(value),quote=True)}"' for key,value in (attrs or {}).items()]
        groups.append(['<'+name]+attributes+['>'])
        if text is not None:line(escape(str(text)))
        if close:line('</'+name+'>')
    line('<!DOCTYPE html>');tag('html',{'lang':'pt-BR'},close=False);tag('head',close=False)
    groups.append(['<meta','charset="utf-8"','>']);groups.append(['<meta','name="viewport"','content="width=device-width,initial-scale=1"','>'])
    tag('title',text=title+' — Chocolates e momentos especiais');tag('style',close=False)
    def css(rules):
        for selector,properties in rules.items():
            line(selector+' {')
            if selector.startswith('@'):css(properties)
            else:
                for key,value in properties.items():groups.append(['  '+key+':','    '+value+';'])
            line('}')
    css(CSS);line('</style>');line('</head>');tag('body',close=False)
    tag('a',{'class':'skip-link','href':'#conteudo'},'Pular para o conteúdo')
    tag('div',{'class':'topline'},'CHOCOLATES PARA TRANSFORMAR PEQUENOS MOMENTOS')
    tag('header',{'class':'header'},close=False);tag('nav',{'class':'container navigation','aria-label':'Navegação principal'},close=False)
    tag('a',{'class':'brand','href':'#inicio'},title,close=False);tag('small',text='Chocolates & presentes');line('</a>')
    tag('div',{'class':'navlinks','id':'links'},close=False)
    for href,label in [('produtos','Produtos'),('historia','Nossa seleção'),('duvidas','Dúvidas')]:tag('a',{'href':'#'+href},label)
    line('</div>');tag('button',{'class':'cart-toggle','type':'button'},'Minha seleção ',close=False);tag('span',{'class':'cart-count','aria-live':'polite'},'0');line('</button>')
    tag('button',{'class':'menu-toggle','type':'button','aria-expanded':'false','aria-controls':'links'},'Menu');line('</nav>');line('</header>')
    tag('main',{'id':'conteudo'},close=False);tag('section',{'class':'container hero','id':'inicio'},close=False);tag('div',close=False)
    tag('span',{'class':'eyebrow'},'Seu próximo momento favorito');tag('h1',text='Um chocolate. Muitas boas histórias.')
    tag('p',{'class':'lead'},'Descubra nossa seleção, escolha seus favoritos e encontre um jeito especial de tornar o dia mais doce.')
    tag('div',{'class':'actions'},close=False);tag('a',{'class':'button','href':'#produtos'},'Explorar produtos');tag('a',{'class':'button secondary','href':'#historia'},'Conhecer a seleção');line('</div>');line('</div>')
    tag('div',{'class':'hero-art','role':'img','aria-label':'Ilustração de chocolate artesanal'},close=False);tag('div',{'class':'chocolate','aria-hidden':'true'});tag('span',{'class':'art-label'},'SABOR QUE MERECE UMA PAUSA');line('</div>');line('</section>')
    tag('div',{'class':'container features'},close=False)
    for symbol,heading,description in [('01','Escolha com carinho','Um favorito para cada ocasião'),('02','Explore a seleção','Sabores que convidam a descobrir'),('03','Monte sua lista','Organize os produtos de que gostou')]:
        tag('div',{'class':'feature'},close=False);tag('span',{'aria-hidden':'true'},symbol);tag('div',close=False);tag('strong',text=heading);tag('small',text=description);line('</div>');line('</div>')
    line('</div>');tag('section',{'class':'container section','id':'produtos'},close=False);tag('div',{'class':'section-heading'},close=False)
    tag('div',close=False);tag('span',{'class':'eyebrow'},'Explore & descubra');tag('h2',text='Encontre seu favorito');line('</div>');tag('p',text='Uma seleção para saborear, compartilhar ou transformar em um presente.');line('</div>')
    groups.append(['<input','class="search"','id="search"','type="search"','placeholder="Buscar um chocolate..."','aria-label="Buscar produtos"','>'])
    tag('div',{'class':'catalog'},close=False)
    for name,price in products:
        tag('article',{'class':'product-card'},close=False);tag('div',{'class':'product-visual','aria-hidden':'true'},close=False);tag('div',{'class':'chocolate'});line('</div>')
        tag('div',{'class':'product-body'},close=False);tag('span',{'class':'eyebrow'},'Seleção especial');tag('h3',text=name)
        tag('p',{'class':'product-description'},'Uma escolha para acompanhar sua pausa ou compartilhar um momento especial.')
        tag('div',{'class':'product-footer'},close=False);tag('span',{'class':'price'},price);tag('button',{'class':'add-button','type':'button','aria-label':'Adicionar '+name+' à seleção'},'+');line('</div>');line('</div>');line('</article>')
    line('</div>');tag('p',{'class':'empty no-results','hidden':''},'Nenhum produto encontrado. Experimente outra busca.');line('</section>')
    tag('section',{'class':'container section','id':'historia'},close=False);tag('div',{'class':'story'},close=False)
    tag('div',close=False);tag('span',{'class':'eyebrow'},'Pequenos rituais');tag('h2',{'class':'story-quote'},'O melhor momento pode começar com uma pequena pausa.');line('</div>')
    tag('div',close=False);tag('p',text='Chocolate combina com tempo para apreciar. Explore os produtos, descubra o que combina com você e transforme a escolha em parte da experiência.');tag('a',{'class':'button secondary','href':'#produtos'},'Voltar à seleção');line('</div>');line('</div>');line('</section>')
    tag('section',{'class':'container section','aria-labelledby':'occasions'},close=False);tag('span',{'class':'eyebrow'},'Para cada ocasião');tag('h2',{'id':'occasions'},'Sempre cabe um gesto especial');tag('div',{'class':'occasion-grid'},close=False)
    for heading,description in [('Sua pausa','Escolha um chocolate e reserve um momento para você.'),('Para compartilhar','Monte uma seleção para acompanhar uma boa conversa.'),('Para presentear','Escolha com atenção e transforme o detalhe em carinho.')]:
        tag('article',{'class':'occasion'},close=False);tag('b',text=heading);tag('p',text=description);line('</article>')
    line('</div>');line('</section>');tag('section',{'class':'container section faq','id':'duvidas'},close=False);tag('span',{'class':'eyebrow'},'Antes de escolher');tag('h2',text='Dúvidas sobre esta página')
    for q,a in [('Como encontro um produto?','Digite parte do nome na busca para filtrar a seleção.'),('Como funciona minha seleção?','O botão + adiciona um item à lista desta página. Você pode removê-lo quando quiser.'),('A seleção realiza uma compra?','Não. A lista serve para organizar os produtos de que você gostou e não processa pagamentos.'),('Onde encontro preços e informações?','Esta página mantém os nomes e valores disponíveis no arquivo de origem. Confirme informações atualizadas antes de comprar.')]:
        tag('details',close=False);tag('summary',text=q);tag('p',text=a);line('</details>')
    line('</section>');line('</main>');tag('footer',{'class':'footer'},close=False);tag('div',{'class':'container footer-grid'},close=False)
    tag('div',close=False);tag('h2',text=title);tag('p',text='Chocolates para os seus melhores momentos.');line('</div>');tag('div',close=False)
    for href,label in [('inicio','Início'),('produtos','Produtos'),('duvidas','Dúvidas')]:tag('a',{'href':'#'+href},label)
    tag('small',text='Lista local. Sem envio de dados ou processamento de pagamentos.');line('</div>');line('</div>');line('</footer>')
    tag('aside',{'class':'cart-panel','hidden':'','aria-label':'Minha seleção'},close=False);tag('div',{'class':'cart-header'},close=False);tag('h2',text='Minha seleção');tag('button',{'class':'close-cart','type':'button','aria-label':'Fechar seleção'},'×');line('</div>');tag('div',{'class':'cart-list'});line('</aside>')
    tag('div',{'class':'toast','role':'status','hidden':''});tag('script',close=False)
    for text in JS.splitlines():line(text)
    line('</script>');line('</body>');line('</html>')
    minimum=len(groups);maximum=sum(map(len,groups))
    if not minimum<=lines<=maximum:raise ValueError(f'Este gerador suporta {minimum} a {maximum} linhas para esse conteúdo, recebeu {lines}.')
    # Join only pieces of the SAME HTML tag or CSS declaration. Script lines,
    # content and order never change; no filler is added to hit the requested count.
    excess=maximum-lines
    for group in sorted(groups,key=len,reverse=True):
        while excess and len(group)>1:
            group[0]=group[0]+' '+group.pop(1);excess-=1
    result='\n'.join(part for group in groups for part in group)+'\n'
    if len(result.splitlines())!=lines:raise RuntimeError('Contagem final não corresponde ao pedido.')
    return result


def build(path,lines=1000):
    path=Path(path).resolve(strict=True)
    if path.suffix.lower() not in ('.html','.htm'):raise ValueError('Escolha um arquivo HTML existente.')
    raw=path.read_bytes()
    try:source=raw.decode('utf-8-sig')
    except UnicodeDecodeError:source=raw.decode('cp1252')
    result=render(source,lines)
    backup=path.with_name(path.name+'.bak-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path,backup)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',dir=path.parent,prefix=path.name+'.nexus-',suffix='.tmp',delete=False) as stream:
        stream.write(result);temp=Path(stream.name)
    temp.replace(path)
    return {'path':str(path),'lines':len(result.splitlines()),'bytes':path.stat().st_size,'backup':str(backup),'strategy':'local_catalog_generator'}

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True);parser.add_argument('--lines',type=int,default=1000)
    args=parser.parse_args();print(json.dumps(build(args.source,args.lines),ensure_ascii=False))
