import os,json,re,time,urllib.request,urllib.parse,sys
OA=os.environ['OPENALEX_API_KEY']
def get(u):
    for a in range(3):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'lit'}),timeout=40))
        except Exception as e: err=str(e)[:60]; time.sleep(3)
    print('FAIL',u[:60],err); return {}
def inv(ix):
    if not ix: return ''
    p={i:w for w,l in ix.items() for i in l}; return ' '.join(p[i] for i in sorted(p))
S=['Implied Volatility Changes and Corporate Bond Returns','Rethinking Capital Structure Arbitrage: A Price Discovery Perspective','The Debt-Equity Spread','Contingent Claims and Hedging of Credit Risk with Equity Options','Stocks versus corporate bonds: A cross-sectional puzzle','Credit Spreads, Leverage and Volatility: A Cointegration Approach','Evaluation of conducting capital structure arbitrage using the multi-period extended Geske-Johnson model','Book-to-Market, Mispricing, and the Cross Section of Corporate Bond Returns','Market Timing and Hedge Ratios', 'Is the CreditGrades Model Useful for Hedging CDSs?','The Volatility Spread and Corporate Bond Returns','Option-implied volatility and corporate bond returns','Common Risk Factors in the Cross-Section of Corporate Bond Returns']
rows={}
print('--- seeds')
for t in S:
    r=get('https://api.openalex.org/works?'+urllib.parse.urlencode({'search':t,'per-page':5,'api_key':OA})).get('results',[])
    m=[w for w in r if re.sub(r'\W','',(w.get('title') or '').lower())[:28]==re.sub(r'\W','',t.lower())[:28]]
    if not m: print('nf',t[:50]); continue
    for w in m: print(w['id'].split('/')[-1],w.get('publication_date'),w.get('type'),w.get('cited_by_count'),(w.get('doi') or '')[16:],(w.get('title') or '')[:60])
    ids='|'.join(w['id'].split('/')[-1] for w in m)
    for x in get('https://api.openalex.org/works?'+urllib.parse.urlencode({'filter':f'cites:{ids},from_publication_date:2023-01-01','sort':'publication_date:desc','per-page':100,'api_key':OA})).get('results',[]):
        k=(x.get('doi') or x['id']).lower(); d=rows.setdefault(k,{'s':set(),'t':x.get('title'),'d':x.get('publication_date'),'v':((x.get('primary_location') or {}).get('source') or {}).get('display_name'),'doi':(x.get('doi') or '')[16:],'a':inv(x.get('abstract_inverted_index')),'au':', '.join(a['author']['display_name'] for a in x.get('authorships',[])[:3])}); d['s'].add(t[:15])
C=r'cds|credit default swap|credit spread|corporate bond|bond return|bond spread|credit risk'; E=r'equity|stock|implied vol|option'; M=r'structural|merton|mispric|arbitrage|hedg|implied|cross-market|trading strateg|convergence|distance'
keep=[]
for k,d in rows.items():
    tl=((d['t'] or '')+' '+d['a']).lower()
    if re.search(C,tl) and re.search(E,tl) and re.search(M,tl): keep.append(d)
keep.sort(key=lambda d:d['d'] or '',reverse=True)
print('--- new candidates',len(keep))
for d in keep[:70]: print(f"{d['d']}|s{len(d['s'])}|{(d['t'] or '')[:88]}|{(d['v'] or '')[:24]}|{d['doi']}|{d['a'][:150]}")
print('--- alt records for missing abstracts')
for t in ['Sideshow or center stage? Information transmission between CDS and equity markets','Is the CreditGrades Model Useful for Hedging CDSs?','Structural Equity Option Pricing: Implications for Credit Risk','Pricing path-dependent equity and credit derivatives within a general hybrid equity-credit framework','Integrating Credit and Equity Markets: A Novel Benefit of Convertible Bonds','Implied Credit Spreads Under Heston Dynamics']:
    r=get('https://api.openalex.org/works?'+urllib.parse.urlencode({'search':t,'per-page':6,'api_key':OA})).get('results',[])
    for w in r:
        if re.sub(r'\W','',(w.get('title') or '').lower())[:25]==re.sub(r'\W','',t.lower())[:25]:
            print('##',w.get('publication_date'),w.get('type'),(w.get('doi') or '')[16:],'|',', '.join(a['author']['display_name'] for a in w.get('authorships',[])[:4]),'|',inv(w.get('abstract_inverted_index'))[:600])
