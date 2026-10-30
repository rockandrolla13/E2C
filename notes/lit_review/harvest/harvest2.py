import os,json,re,time,urllib.request,urllib.parse,sys
OA=os.environ['OPENALEX_API_KEY']; S2=os.environ['S2_API_KEY']
SEEDS=['How Profitable Is Capital Structure Arbitrage?','Capital Structure Arbitrage: Model Choice and Volatility Calibration','Risk and Return in Fixed Income Arbitrage: Nickels in Front of a Steamroller?','Individual Stock-Option Prices and Credit Spreads','A Simple Robust Link Between American Puts and Credit Protection','Limits to Arbitrage and Cross-Market Pricing Discrepancies','Limited Arbitrage between Equity and Credit Markets','Anchoring Credit Default Swap Spreads to Firm Fundamentals','The Cross-Section of Credit Risk Premia and Equity Returns','Market Timing and Hedge Ratios of Corporate Bonds','Corporate Bond Returns and the Merton Model','Hedge Ratios in Structural Models','Structural Models of Corporate Bond Pricing: An Empirical Analysis','Structural GARCH: The Volatility-Leverage Connection','The Information Content of CDS Implied Volatility and Associated Trading Strategies','Price convergence between credit default swap and put option','Equity Volatility and Corporate Bond Yields','The Relation between Implied and Realised Volatility in Credit']
def get(u,h=None,n=5):
    for a in range(n):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=h or {'User-Agent':'lit'}),timeout=40))
        except Exception as e: err=str(e)[:70]; time.sleep(4*(a+1))
    print('FAIL',u[:70],err,file=sys.stderr); return {}
def inv(ix):
    if not ix: return ''
    p={i:w for w,l in ix.items() for i in l}; return ' '.join(p[i] for i in sorted(p))
rows={}
def add(k,seed,**v):
    d=rows.setdefault(k,{'seeds':set(),'src':set()}); d['seeds'].add(seed); d['src'].add(v.pop('s'))
    for a,b in v.items():
        if b and (not d.get(a) or (a=='abstract' and len(b)>len(d[a]))): d[a]=b
sk={}
for t in SEEDS:
    r=get('https://api.openalex.org/works?'+urllib.parse.urlencode({'search':t,'per-page':3,'api_key':OA})).get('results',[])
    m=[w for w in r if re.sub(r'\W','',(w.get('title') or '').lower())[:30]==re.sub(r'\W','',t.lower())[:30]]
    if not m: print('seed not found OA:',t); continue
    w=max(m,key=lambda x:x.get('cited_by_count') or 0); wid=w['id'].split('/')[-1]; sk[t]=wid
    print('seed',wid,w.get('publication_year'),w.get('cited_by_count'),t[:50])
    u='https://api.openalex.org/works?'+urllib.parse.urlencode({'filter':f'cites:{wid},from_publication_date:2022-01-01','sort':'publication_date:desc','per-page':100,'api_key':OA})
    for x in get(u).get('results',[]):
        doi=(x.get('doi') or '').replace('https://doi.org/','').lower(); k=doi or re.sub(r'\W+','',(x.get('title') or '').lower())[:80]
        add(k,t[:22],s='OA',title=x.get('title'),date=x.get('publication_date'),venue=((x.get('primary_location') or {}).get('source') or {}).get('display_name'),doi=doi,abstract=inv(x.get('abstract_inverted_index')),authors=', '.join(a['author']['display_name'] for a in x.get('authorships',[])[:4]),cited=x.get('cited_by_count'),oa=(x.get('open_access') or {}).get('oa_url'),type=x.get('type'))
    time.sleep(.2)
H={'x-api-key':S2,'User-Agent':'lit'}
for t in SEEDS:
    time.sleep(3)
    r=get('https://api.semanticscholar.org/graph/v1/paper/search/match?'+urllib.parse.urlencode({'query':t,'fields':'paperId,title'}),H,3).get('data') or []
    if not r: print('seed not found S2:',t); continue
    pid=r[0]['paperId']; time.sleep(3)
    c=get(f'https://api.semanticscholar.org/graph/v1/paper/{pid}/citations?fields=title,year,publicationDate,abstract,venue,authors,externalIds,openAccessPdf,citationCount&limit=1000',H,3).get('data') or []
    n=0
    for e in c:
        x=e.get('citingPaper') or {}
        if (x.get('year') or 0)<2022: continue
        n+=1; doi=((x.get('externalIds') or {}).get('DOI') or '').lower(); k=doi or re.sub(r'\W+','',(x.get('title') or '').lower())[:80]
        add(k,t[:22],s='S2',title=x.get('title'),date=x.get('publicationDate') or str(x.get('year')),venue=x.get('venue'),doi=doi,abstract=x.get('abstract'),authors=', '.join(a['name'] for a in (x.get('authors') or [])[:4]),cited=x.get('citationCount'),oa=(x.get('openAccessPdf') or {}).get('url'))
    print('S2',t[:40],'citing>=2022',n)
print('unique',len(rows))
CR=r'cds|credit default swap|credit spread|corporate bond|bond return|bond spread|credit risk|yield spread'; EQ=r'equity|stock|implied vol|option|volatility'; 
c=[]
for k,d in rows.items():
    tl=((d.get('title') or '')+' '+(d.get('abstract') or '')).lower()
    if not (re.search(CR,tl) and re.search(EQ,tl)): continue
    d['key']=k; d['nseeds']=len(d['seeds']); d['seeds']=sorted(d['seeds']); d['src']=sorted(d['src']); c.append(d)
c.sort(key=lambda d:d.get('date') or '',reverse=True)
json.dump(c,open(sys.argv[1],'w'),indent=1)
print('candidates',len(c))
for d in c[:130]:
    print(f"{(d.get('date') or '')[:10]}|s{d['nseeds']}|{'+'.join(d['src'])}|{(d.get('title') or '')[:90]}|{(d.get('venue') or '')[:26]}|{d.get('doi') or ''}|{(d.get('abstract') or '')[:130]}")
