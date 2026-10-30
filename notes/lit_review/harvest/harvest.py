import os,json,re,time,urllib.request,urllib.parse,sys
OUT=sys.argv[1]; OA=os.environ['OPENALEX_API_KEY']; S2=os.environ['S2_API_KEY']
Q=['"capital structure arbitrage"','"equity-to-credit"','"credit-equity" arbitrage','CreditGrades','"credit default swap" "equity volatility" mispricing','"CDS" "implied volatility" structural model trading strategy','"corporate bond" equity "structural model" mispricing','"credit-implied volatility"','"CDS" "put option" convergence arbitrage','"debt" "equity" "relative value" "credit spread" structural','"bond" "equity" cross-market mispricing "Merton"','"distance to default" "bond returns"','"credit spreads" "equity options" "implied volatility" corporate bonds cross-section','"CDS" "equity" "lead-lag" mispricing trading']
def get(u,h=None):
    for a in range(4):
        try:
            r=urllib.request.Request(u,headers=h or {'User-Agent':'lit-review'})
            return json.load(urllib.request.urlopen(r,timeout=40))
        except Exception as e:
            err=str(e)[:80]; time.sleep(3*(a+1))
    print('FAIL',u.split('?')[0],err,file=sys.stderr); return {}
def inv(ix):
    if not ix: return ''
    p={}
    for w,l in ix.items():
        for i in l: p[i]=w
    return ' '.join(p[i] for i in sorted(p))
rows={}
def add(k,**v):
    d=rows.setdefault(k,{'sources':set()}); d['sources'].add(v.pop('source'))
    for a,b in v.items():
        if b and (not d.get(a) or (a=='abstract' and len(b)>len(d[a]))): d[a]=b
n=[0,0]
for q in Q:
    u='https://api.openalex.org/works?'+urllib.parse.urlencode({'search':q,'filter':'from_publication_date:2021-01-01','sort':'relevance_score:desc','per-page':100,'api_key':OA})
    for w in get(u).get('results',[]):
        n[0]+=1; doi=(w.get('doi') or '').replace('https://doi.org/','').lower()
        k=doi or re.sub(r'\W+','',(w.get('title') or '').lower())[:80]
        add(k,source='OA',title=w.get('title'),date=w.get('publication_date'),venue=((w.get('primary_location') or {}).get('source') or {}).get('display_name'),doi=doi,abstract=inv(w.get('abstract_inverted_index')),authors=', '.join(a['author']['display_name'] for a in w.get('authorships',[])[:4]),cited=w.get('cited_by_count'),oa=(w.get('open_access') or {}).get('oa_url'),type=w.get('type'))
    u='https://api.semanticscholar.org/graph/v1/paper/search/bulk?'+urllib.parse.urlencode({'query':q,'year':'2021-','fields':'title,year,publicationDate,abstract,venue,authors,externalIds,openAccessPdf,citationCount,publicationTypes'})
    for w in (get(u,{'x-api-key':S2,'User-Agent':'lit-review'}).get('data') or [])[:300]:
        n[1]+=1; e=w.get('externalIds') or {}; doi=(e.get('DOI') or '').lower()
        k=doi or re.sub(r'\W+','',(w.get('title') or '').lower())[:80]
        add(k,source='S2',title=w.get('title'),date=w.get('publicationDate') or str(w.get('year') or ''),venue=w.get('venue'),doi=doi,abstract=w.get('abstract'),authors=', '.join(a['name'] for a in (w.get('authors') or [])[:4]),cited=w.get('citationCount'),oa=(w.get('openAccessPdf') or {}).get('url'))
    time.sleep(1.1)
print('raw hits OA,S2',n,'unique',len(rows))
STRONG=r'capital[- ]structure arbitrage|equity[- ]to[- ]credit|creditgrades|credit grades|credit[- ]implied vol|cds[- ]implied|implied by (the )?cds|cross[- ]market (mispricing|arbitrage)|credit[- ]equity|equity[- ]credit|debt[- ]equity (relative|arbitrage|mispric)'
LINK=r'(cds|credit default swap|credit spread|corporate bond|bond return|bond spread)'; EQ=r'(equity|stock|implied vol|option)'; MECH=r'(structural|merton|mispric|arbitrage|convergence|distance[- ]to[- ]default|trading strateg|relative value|lead[- ]lag|return predict|predict)'
c=[]
for k,d in rows.items():
    t=(d.get('title') or '')+' '+(d.get('abstract') or ''); tl=t.lower(); ti=(d.get('title') or '').lower()
    s=3*len(re.findall(STRONG,tl))+(4 if re.search(STRONG,ti) else 0)
    both=re.search(LINK,tl) and re.search(EQ,tl) and re.search(MECH,tl)
    if s or (both and re.search(LINK,ti) and re.search(EQ+'|'+MECH,ti)):
        d['key']=k; d['score']=s+(1 if both else 0); d['sources']=sorted(d['sources']); c.append(d)
c.sort(key=lambda d:d.get('date') or '',reverse=True)
json.dump(c,open(OUT,'w'),indent=1,default=list)
print('candidates',len(c))
for d in c[:90]:
    print(f"{(d.get('date') or '')[:10]}|{d['score']}|{'+'.join(d['sources'])}|{(d.get('title') or '')[:95]}|{(d.get('venue') or '')[:32]}|{d.get('doi') or ''}|{(d.get('abstract') or '')[:170]}")
