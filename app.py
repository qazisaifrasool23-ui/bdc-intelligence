import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf
import json
from datetime import datetime

st.set_page_config(page_title="BDC Intelligence.AI", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated:
        return True
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("""
        <div style='text-align:center; margin-bottom:32px;'>
            <div style='font-size:36px; font-weight:700; color:#0F1923; letter-spacing:-1px; margin-bottom:6px;'>
                BDC Intelligence<span style='color:#1A6EF2;'>.AI</span>
            </div>
            <div style='font-size:14px; color:#7A8899;'>Private Credit Analytics Platform</div>
            <div style='margin-top:12px; display:inline-block; background:#EBF2FF; color:#1A6EF2;
                font-size:11px; font-weight:600; padding:3px 12px; border-radius:20px;'>
                BETA — Selected Access Only
            </div>
        </div>
        """, unsafe_allow_html=True)
        password = st.text_input("Access Code", type="password", placeholder="Enter your beta access code", label_visibility="collapsed")
        col_a, col_b, col_c = st.columns([1,2,1])
        with col_b:
            if st.button("Access Platform →", use_container_width=True, type="primary"):
                if password == st.secrets.get("BETA_PASSWORD", "bdcbeta2026"):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect access code.")
        st.markdown("""
        <div style='text-align:center; margin-top:24px; font-size:11px; color:#B0BACC;'>
            Covering 45 publicly traded BDCs · Data extracted from SEC EDGAR filings
        </div>
        """, unsafe_allow_html=True)
    return False

if not check_password():
    st.stop()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500;600&family=Geist:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Geist', sans-serif !important; }
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }
.main .block-container { padding: 1.5rem 2rem; max-width: 100%; }
.stApp { background: #F7F8FA; }
section[data-testid="stSidebar"] { background: white !important; border-right: 1px solid #E2E5EB !important; }
div[data-testid="metric-container"] { background: white; border: 1px solid #E2E5EB; border-radius: 10px; padding: 16px !important; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.stTabs [data-baseweb="tab-list"] { background: white; border-radius: 10px; border: 1px solid #E2E5EB; padding: 4px; gap: 2px; }
.stTabs [data-baseweb="tab"] { border-radius: 7px; font-weight: 500; font-size: 13px; color: #7A8899; }
.stTabs [aria-selected="true"] { background: #F7F8FA !important; color: #0F1923 !important; }
.stDataFrame { border-radius: 10px; overflow: hidden; border: 1px solid #E2E5EB; }
.stButton > button { border-radius: 8px; font-weight: 500; font-size: 13px; }
.bdc-card { background: white; border: 1px solid #E2E5EB; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 16px; }
.alert-box { padding: 12px 16px; border-radius: 10px; margin-bottom: 8px; border-left: 3px solid; }
.alert-red { background:#FDECEA; border-color:#D93025; }
.alert-amber { background:#FEF3C7; border-color:#D97706; }
.alert-blue { background:#EBF2FF; border-color:#1A6EF2; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def load_bdc_data():
    with open("bdc_data.json") as f:
        data = json.load(f)
    return pd.DataFrame(data)

@st.cache_data(ttl=3600)
def fetch_prices(tickers):
    prices = {}
    try:
        tickers_str = " ".join(tickers)
        data = yf.download(tickers_str, period="1d", progress=False, threads=True)
        if len(tickers) == 1:
            prices[tickers[0]] = float(data['Close'].iloc[-1])
        else:
            for t in tickers:
                try:
                    prices[t] = float(data['Close'][t].iloc[-1])
                except:
                    prices[t] = None
    except:
        pass
    return prices

def fmt(v, fmt_type="num", decimals=2):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "N/A"
    if fmt_type == "pct": return f"{v:.1f}%"
    if fmt_type == "x": return f"{v:.2f}×"
    if fmt_type == "dollar": return f"${v:.2f}"
    if fmt_type == "mn": return f"${v:,.0f}M"
    return f"{v:.{decimals}f}"

def grade_color(g):
    return {'A':'#0E9E60','B':'#1A6EF2','C':'#D97706','D':'#D93025','F':'#D93025'}.get(g,'#7A8899')

def grade_bg(g):
    return {'A':'#E6F7EF','B':'#EBF2FF','C':'#FEF3C7','D':'#FDECEA','F':'#FDECEA'}.get(g,'#F7F8FA')

def sentiment_label(s):
    if s is None: return "N/A"
    if s >= 4.5: return "🟢 Confident"
    if s >= 3.5: return "🔵 Neutral"
    if s >= 2.5: return "🟡 Cautious"
    return "🔴 Bearish"

df = load_bdc_data()
tickers = df['ticker'].tolist()

with st.spinner("Fetching live market prices..."):
    prices = fetch_prices(tickers)

df['price'] = df['ticker'].map(prices)
df['pnav'] = df.apply(lambda r: round(r['price']/r['nav_per_share'],2) if r['price'] and r['nav_per_share'] else None, axis=1)
df['div_yield_market'] = df.apply(lambda r: round((r['dividend_per_share']*4/r['price'])*100,1) if r['price'] and r['dividend_per_share'] else None, axis=1)

with st.sidebar:
    st.markdown("""
    <div style='padding:8px 4px 16px; border-bottom:1px solid #E2E5EB; margin-bottom:16px;'>
        <div style='font-size:18px; font-weight:700; color:#0F1923; letter-spacing:-0.5px;'>
            BDC Intelligence<span style='color:#1A6EF2;'>.AI</span>
        </div>
        <div style='font-size:11px; color:#B0BACC; margin-top:2px;'>Private Credit Analytics</div>
    </div>
    """, unsafe_allow_html=True)
    now = datetime.now().strftime("%H:%M EST")
    st.markdown(f"""
    <div style='display:flex; align-items:center; gap:6px; margin-bottom:16px;
        background:#E6F7EF; border-radius:8px; padding:6px 10px;'>
        <div style='width:6px;height:6px;border-radius:50%;background:#0E9E60;'></div>
        <span style='font-size:11px;font-weight:600;color:#0E9E60;'>LIVE</span>
        <span style='font-size:11px;color:#7A8899;margin-left:auto;'>{now}</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("**Navigation**")
    page = st.radio("page", ["🌐 Universe", "🔍 Fund Deep Dive", "⚡ Screener", "↔ Compare"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown("**Universe Pulse**")
    valid_na = df['na_pct_cost'].dropna()
    valid_pik = df['pik_pct'].dropna()
    valid_lev = df['leverage'].dropna()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Avg NA%", f"{valid_na.mean():.1f}%")
        st.metric("Avg PIK%", f"{valid_pik.mean():.1f}%")
    with col2:
        st.metric("Avg Lev", f"{valid_lev.mean():.2f}×")
        grade_counts = df['grade'].value_counts()
        ab = grade_counts.get('A',0) + grade_counts.get('B',0)
        st.metric("A/B Funds", f"{ab}/45")
    st.markdown("---")
    st.markdown("**Jump to Fund**")
    selected_ticker = st.selectbox("Jump to fund", [""]+sorted(df['ticker'].tolist()), format_func=lambda x: x if x else "Select a fund...")
    if selected_ticker:
        page = "🔍 Fund Deep Dive"
    st.markdown("---")
    st.markdown("""
    <div style='font-size:10px; color:#B0BACC; line-height:1.6;'>
        Data: SEC EDGAR filings<br>
        Prices: Yahoo Finance (live)<br>
        Coverage: 45 publicly traded BDCs<br>
        Last filing period: Q3/Q4 2025
    </div>
    """, unsafe_allow_html=True)

if page == "🌐 Universe":
    st.markdown("""
    <div style='margin-bottom:20px;'>
        <div style='font-size:22px;font-weight:700;color:#0F1923;letter-spacing:-0.5px;'>BDC Universe</div>
        <div style='font-size:13px;color:#7A8899;margin-top:2px;'>45 publicly traded Business Development Companies · Data from SEC EDGAR filings</div>
    </div>
    """, unsafe_allow_html=True)
    high_na = df[df['na_pct_cost']>7]['ticker'].tolist()
    high_pik = df[(df['pik_pct'].notna())&(df['pik_pct']>15)]['ticker'].tolist()
    low_cov = df[(df['nii_coverage'].notna())&(df['nii_coverage']<0.95)]['ticker'].tolist()
    col1, col2, col3 = st.columns(3)
    with col1:
        if high_na:
            st.markdown(f"<div class='alert-box alert-red'><div style='font-size:11px;font-weight:600;color:#D93025;margin-bottom:3px;'>⚠ HIGH NON-ACCRUAL</div><div style='font-size:12px;color:#3D4D5C;'>{len(high_na)} funds above 7% — {', '.join(high_na[:4])}</div></div>", unsafe_allow_html=True)
    with col2:
        if high_pik:
            st.markdown(f"<div class='alert-box alert-amber'><div style='font-size:11px;font-weight:600;color:#D97706;margin-bottom:3px;'>⚡ ELEVATED PIK INCOME</div><div style='font-size:12px;color:#3D4D5C;'>{len(high_pik)} funds above 15% — {', '.join(high_pik[:4])}</div></div>", unsafe_allow_html=True)
    with col3:
        if low_cov:
            st.markdown(f"<div class='alert-box alert-blue'><div style='font-size:11px;font-weight:600;color:#1A6EF2;margin-bottom:3px;'>📋 NII COVERAGE RISK</div><div style='font-size:12px;color:#3D4D5C;'>{len(low_cov)} funds below 0.95× — {', '.join(low_cov[:4])}</div></div>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns([2,1,1,1])
    with col1:
        grade_filter = st.multiselect("Grade", ["A","B","C","D","F"], default=["A","B","C","D","F"], label_visibility="collapsed")
    with col2:
        sort_by = st.selectbox("Sort by", ["na_pct_cost","pik_pct","leverage","nii_coverage","nav_per_share"], format_func=lambda x: {"na_pct_cost":"Non-Accrual %","pik_pct":"PIK %","leverage":"Leverage","nii_coverage":"NII Coverage","nav_per_share":"NAV/Share"}[x])
    with col3:
        min_na = st.number_input("Max NA%", min_value=0.0, max_value=20.0, value=20.0, step=0.5)
    with col4:
        show_count = st.selectbox("Show", [20,35,45], index=2)
    filtered = df[df['grade'].isin(grade_filter)].copy()
    filtered = filtered[filtered['na_pct_cost'].fillna(0)<=min_na]
    filtered = filtered.sort_values(sort_by, ascending=True).head(show_count)
    rows_html = []
    for _, r in filtered.iterrows():
        g = r['grade']
        price_str = f"${r['price']:.2f}" if r['price'] else "N/A"
        pnav_str = fmt(r['pnav'],'x') if r['pnav'] else "N/A"
        def cn(val, lo1, lo2): 
            if val is None: return "#7A8899"
            return "#D93025" if val>lo1 else "#D97706" if val>lo2 else "#0E9E60"
        na_c = cn(r['na_pct_cost'],7,3); pik_c = cn(r['pik_pct'],15,8); lev_c = cn(r['leverage'],2.0,1.6)
        cov_val = r['nii_coverage']; cov_c = "#D93025" if (cov_val and cov_val<0.95) else "#D97706" if (cov_val and cov_val<1.05) else "#0E9E60"
        rows_html.append(f"""<tr style='border-bottom:1px solid #E2E5EB;' onmouseover="this.style.background='#F7F8FA'" onmouseout="this.style.background='white'">
            <td style='padding:10px 12px;font-family:Geist Mono,monospace;font-weight:600;font-size:13px;'>{r['ticker']}</td>
            <td style='padding:10px 8px;'><span style='background:{grade_bg(g)};color:{grade_color(g)};font-family:Geist Mono,monospace;font-size:11px;font-weight:600;padding:2px 8px;border-radius:4px;'>{g}</span></td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;'>{price_str}</td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;'>{fmt(r['nav_per_share'],'dollar')}</td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;'>{pnav_str}</td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;color:{na_c};font-weight:500;'>{fmt(r['na_pct_cost'],'pct')}</td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;color:{pik_c};font-weight:500;'>{fmt(r['pik_pct'],'pct')}</td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;color:{lev_c};font-weight:500;'>{fmt(r['leverage'],'x')}</td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;'>{fmt(r['div_yield_market'],'pct') if r.get('div_yield_market') else 'N/A'}</td>
            <td style='padding:10px 8px;font-family:Geist Mono,monospace;font-size:12px;text-align:right;color:{cov_c};font-weight:500;'>{fmt(r['nii_coverage'],'x')}</td>
            <td style='padding:10px 8px;font-size:11px;color:#7A8899;text-align:right;'>{r['quarter']}</td>
        </tr>""")
    st.markdown(f"""<div style='background:white;border:1px solid #E2E5EB;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06);'>
        <div style='padding:14px 16px;border-bottom:1px solid #E2E5EB;display:flex;justify-content:space-between;align-items:center;'>
            <span style='font-size:13px;font-weight:600;color:#0F1923;'>{len(filtered)} Funds</span>
            <span style='font-size:12px;color:#7A8899;'>Prices live · Filing data as of most recent 10-Q</span>
        </div>
        <div style='overflow-x:auto;'><table style='width:100%;border-collapse:collapse;'>
        <thead><tr style='background:#F7F8FA;border-bottom:1px solid #E2E5EB;'>
            {''.join(f"<th style='padding:8px 12px;text-align:{'left' if i<2 else 'right'};font-size:10px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#7A8899;'>{h}</th>" for i,h in enumerate(['Ticker','Grade','Price','NAV/Sh','P/NAV','NA% Cost','PIK%','Leverage','Div Yield','NII Cov','Period']))}
        </tr></thead>
        <tbody>{''.join(rows_html)}</tbody></table></div></div>""", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns([1,2])
    with col1:
        gc = df['grade'].value_counts().reindex(['A','B','C','D','F'],fill_value=0)
        fig = go.Figure(go.Bar(x=gc.index, y=gc.values, marker_color=['#0E9E60','#1A6EF2','#D97706','#D93025','#9B1C1C'], text=gc.values, textposition='outside'))
        fig.update_layout(title="Grade Distribution", height=280, margin=dict(l=20,r=20,t=40,b=20), plot_bgcolor='white', paper_bgcolor='white', yaxis=dict(gridcolor='#E2E5EB'), font=dict(family='Geist, sans-serif',size=12), title_font_size=13)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        sdf = df[df['na_pct_cost'].notna()&df['pik_pct'].notna()].copy()
        fig2 = px.scatter(sdf, x='pik_pct', y='na_pct_cost', text='ticker', color='grade', color_discrete_map={'A':'#0E9E60','B':'#1A6EF2','C':'#D97706','D':'#D93025','F':'#9B1C1C'}, title='PIK% vs Non-Accrual% — Universe Map', labels={'pik_pct':'PIK % of Income','na_pct_cost':'Non-Accrual % at Cost'})
        fig2.update_traces(textposition='top center', textfont_size=9)
        fig2.update_layout(height=280, margin=dict(l=20,r=20,t=40,b=20), plot_bgcolor='white', paper_bgcolor='white', xaxis=dict(gridcolor='#E2E5EB'), yaxis=dict(gridcolor='#E2E5EB'), font=dict(family='Geist, sans-serif',size=12), title_font_size=13, legend=dict(orientation='h',yanchor='bottom',y=1.02))
        st.plotly_chart(fig2, use_container_width=True)

elif page == "🔍 Fund Deep Dive":
    if selected_ticker:
        fund_ticker = selected_ticker
    else:
        fund_ticker = st.selectbox("Select Fund", sorted(df['ticker'].tolist()), index=sorted(df['ticker'].tolist()).index('TCPC') if 'TCPC' in df['ticker'].values else 0)
    r = df[df['ticker']==fund_ticker].iloc[0]
    g = r['grade']
    price = r['price']
    pnav = r['pnav']
    st.markdown(f"""
    <div class='bdc-card'>
        <div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;'>
            <div>
                <div style='font-size:22px;font-weight:700;color:#0F1923;letter-spacing:-0.5px;margin-bottom:6px;'>
                    {fund_ticker} <span style='font-size:14px;font-weight:400;color:#7A8899;margin-left:8px;'>{r['quarter']}</span>
                </div>
                <div style='display:flex;gap:8px;flex-wrap:wrap;'>
                    <span style='font-size:11px;padding:2px 8px;border-radius:4px;background:#F0F2F5;color:#3D4D5C;border:1px solid #E2E5EB;'>AUM: {fmt(r['net_assets_mn'],"mn") if r['net_assets_mn'] else "N/A"}</span>
                    <span style='font-size:11px;padding:2px 8px;border-radius:4px;background:#F0F2F5;color:#3D4D5C;border:1px solid #E2E5EB;'>{int(r['num_portfolio_companies']) if r['num_portfolio_companies'] else "N/A"} portfolio cos</span>
                    <span style='font-size:11px;padding:2px 8px;border-radius:4px;background:#F0F2F5;color:#3D4D5C;border:1px solid #E2E5EB;'>Sentiment: {sentiment_label(r['sentiment_score'])}</span>
                </div>
            </div>
            <div style='display:flex;gap:16px;align-items:flex-start;'>
                <div style='text-align:right;'>
                    <div style='font-family:Geist Mono,monospace;font-size:26px;font-weight:600;color:#0F1923;'>{f"${price:.2f}" if price else "N/A"}</div>
                    <div style='font-size:12px;color:#7A8899;margin-top:2px;'>P/NAV: {fmt(pnav,"x") if pnav else "N/A"}</div>
                </div>
                <div style='width:56px;height:56px;border-radius:12px;background:{grade_bg(g)};border:1px solid rgba(0,0,0,0.08);display:flex;flex-direction:column;align-items:center;justify-content:center;'>
                    <div style='font-family:Geist Mono,monospace;font-size:22px;font-weight:700;color:{grade_color(g)};line-height:1;'>{g}</div>
                    <div style='font-size:8px;color:#B0BACC;letter-spacing:0.08em;margin-top:2px;'>GRADE</div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    col1,col2,col3,col4,col5 = st.columns(5)
    kpis = [
        (col1,"Non-Accrual % Cost",r['na_pct_cost'],"pct","🔴" if (r['na_pct_cost'] or 0)>7 else "🟡" if (r['na_pct_cost'] or 0)>3 else "🟢"),
        (col2,"Non-Accrual % FV",r['na_pct_fv'],"pct","🔴" if (r['na_pct_fv'] or 0)>5 else "🟡" if (r['na_pct_fv'] or 0)>2 else "🟢"),
        (col3,"PIK % of Income",r['pik_pct'],"pct","🔴" if (r['pik_pct'] or 0)>15 else "🟡" if (r['pik_pct'] or 0)>8 else "🟢"),
        (col4,"Leverage",r['leverage'],"x","🔴" if (r['leverage'] or 0)>2.0 else "🟡" if (r['leverage'] or 0)>1.6 else "🟢"),
        (col5,"NII Coverage",r['nii_coverage'],"x","🔴" if (r['nii_coverage'] or 1)<0.95 else "🟡" if (r['nii_coverage'] or 1)<1.05 else "🟢"),
    ]
    for col,label,val,ft,signal in kpis:
        with col:
            st.metric(label, f"{signal} {fmt(val,ft)}")
    st.markdown("<br>", unsafe_allow_html=True)
    col1,col2,col3,col4,col5 = st.columns(5)
    with col1: st.metric("NAV / Share", fmt(r['nav_per_share'],'dollar'))
    with col2: st.metric("NII / Share", fmt(r['nii_per_share'],'dollar'))
    with col3: st.metric("Div / Share (Qtr)", fmt(r['dividend_per_share'],'dollar'))
    with col4: st.metric("Wtd Avg Yield", fmt(r['weighted_avg_yield'],'pct'))
    with col5: st.metric("Implied Recovery", fmt(r['implied_recovery_rate'],'pct'))
    st.markdown("<br>", unsafe_allow_html=True)
    col1,col2 = st.columns(2)
    with col1:
        peer_na = df[['ticker','na_pct_cost']].dropna().sort_values('na_pct_cost')
        colors_na = ['#D93025' if t==fund_ticker else '#D97706' if v>5 else '#1A6EF2' for t,v in zip(peer_na['ticker'],peer_na['na_pct_cost'])]
        fig_na = go.Figure(go.Bar(y=peer_na['ticker'],x=peer_na['na_pct_cost'],orientation='h',marker_color=colors_na,text=[f"{v:.1f}%" for v in peer_na['na_pct_cost']],textposition='outside'))
        fig_na.update_layout(title="Non-Accrual % at Cost — All Funds",height=500,margin=dict(l=60,r=40,t=40,b=20),plot_bgcolor='white',paper_bgcolor='white',xaxis=dict(gridcolor='#E2E5EB',ticksuffix='%'),font=dict(family='Geist, sans-serif',size=10),title_font_size=13)
        st.plotly_chart(fig_na, use_container_width=True)
    with col2:
        peer_pik = df[['ticker','pik_pct']].dropna().sort_values('pik_pct')
        colors_pik = ['#D93025' if t==fund_ticker else '#D97706' if v>10 else '#1A6EF2' for t,v in zip(peer_pik['ticker'],peer_pik['pik_pct'])]
        fig_pik = go.Figure(go.Bar(y=peer_pik['ticker'],x=peer_pik['pik_pct'],orientation='h',marker_color=colors_pik,text=[f"{v:.1f}%" for v in peer_pik['pik_pct']],textposition='outside'))
        fig_pik.update_layout(title="PIK % of Income — All Funds",height=500,margin=dict(l=60,r=40,t=40,b=20),plot_bgcolor='white',paper_bgcolor='white',xaxis=dict(gridcolor='#E2E5EB',ticksuffix='%'),font=dict(family='Geist, sans-serif',size=10),title_font_size=13)
        st.plotly_chart(fig_pik, use_container_width=True)
    st.markdown("""<div style='font-size:14px;font-weight:600;color:#0F1923;margin:8px 0 12px;display:flex;align-items:center;gap:8px;'>
        <span style='background:#F5F0FF;color:#7C3AED;font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;letter-spacing:0.04em;'>AI</span>
        MD&A Intelligence</div>""", unsafe_allow_html=True)
    mda = r.get('mda_summary','')
    if mda and len(str(mda))>10:
        st.markdown(f"""<div class='bdc-card' style='border-left:3px solid #1A6EF2;'>
            <div style='font-size:13px;color:#3D4D5C;line-height:1.7;margin-bottom:12px;'>{mda}</div>
            <div style='font-size:10px;color:#B0BACC;'>Source: {r['quarter']} 10-Q · SEC EDGAR · Extracted via AI</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.info("MD&A summary not available for this fund.")
    st.markdown("""<div style='background:linear-gradient(135deg,#F5F0FF,#EBF2FF);border:1px solid rgba(124,58,237,0.2);border-radius:12px;padding:20px;margin-top:16px;text-align:center;'>
        <div style='font-size:16px;font-weight:600;color:#0F1923;margin-bottom:6px;'>✦ Ask Nexus AI</div>
        <div style='font-size:13px;color:#7A8899;margin-bottom:12px;line-height:1.6;'>Query all 45 BDC filings in plain English.<br>
        <em>"Which funds mentioned covenant amendments in Q3?"</em></div>
        <div style='display:inline-block;background:#7C3AED;color:white;font-size:12px;font-weight:600;padding:8px 20px;border-radius:8px;'>Available in Pro Plan — Coming Soon</div>
        <div style='font-size:11px;color:#B0BACC;margin-top:10px;'>Powered by RAG over 1,430 SEC filings · Anthropic Claude</div>
    </div>""", unsafe_allow_html=True)

elif page == "⚡ Screener":
    st.markdown("<div style='font-size:22px;font-weight:700;color:#0F1923;letter-spacing:-0.5px;margin-bottom:20px;'>Fund Screener</div>", unsafe_allow_html=True)
    col_filter, col_results = st.columns([1,2.5])
    with col_filter:
        st.markdown("**Filter Criteria**")
        min_grade = st.selectbox("Minimum Grade",["Any","A","B","C","D"],index=0)
        max_na = st.slider("Max Non-Accrual %",0.0,15.0,15.0,0.5)
        max_pik = st.slider("Max PIK %",0.0,30.0,30.0,1.0)
        max_lev = st.slider("Max Leverage",0.5,3.5,3.5,0.1)
        min_cov = st.slider("Min NII Coverage",0.0,2.0,0.0,0.05)
        st.markdown("---")
        st.markdown("**Quick Screens**")
        clean = st.button("✓ Clean Income", use_container_width=True)
        danger = st.button("⚠ Danger Zone", use_container_width=True)
    with col_results:
        screened = df.copy()
        grade_order = ['A','B','C','D','F']
        if min_grade != "Any":
            allowed = grade_order[grade_order.index(min_grade):]
            screened = screened[screened['grade'].isin(allowed)]
        if clean:
            screened = screened[(screened['na_pct_cost'].fillna(99)<2)&(screened['pik_pct'].fillna(99)<5)&(screened['nii_coverage'].fillna(0)>1.1)]
        elif danger:
            screened = screened[(screened['na_pct_cost'].fillna(0)>7)|(screened['pik_pct'].fillna(0)>15)]
        else:
            screened = screened[screened['na_pct_cost'].fillna(0)<=max_na]
            screened = screened[screened['pik_pct'].fillna(0)<=max_pik]
            screened = screened[screened['leverage'].fillna(1.5)<=max_lev]
            screened = screened[screened['nii_coverage'].fillna(1.0)>=min_cov]
        st.markdown(f"**{len(screened)} funds match**")
        if len(screened)>0:
            disp = screened[['ticker','grade','na_pct_cost','pik_pct','leverage','nii_coverage','nav_per_share','price','pnav']].copy()
            disp.columns = ['Ticker','Grade','NA% Cost','PIK%','Leverage','NII Cov','NAV/Sh','Price','P/NAV']
            for col in ['NA% Cost','PIK%','Leverage','NII Cov','NAV/Sh','Price','P/NAV']:
                if col in disp.columns:
                    disp[col] = disp[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")
            st.dataframe(disp, use_container_width=True, hide_index=True)
        else:
            st.info("No funds match. Try relaxing the filters.")

elif page == "↔ Compare":
    st.markdown("<div style='font-size:22px;font-weight:700;color:#0F1923;letter-spacing:-0.5px;margin-bottom:20px;'>Side-by-Side Comparison</div>", unsafe_allow_html=True)
    all_tickers = sorted(df['ticker'].tolist())
    defaults = [t for t in ['ARCC','TCPC','MAIN'] if t in all_tickers]
    selected = st.multiselect("Select funds to compare (2–4)", all_tickers, default=defaults, max_selections=4)
    if len(selected)<2:
        st.warning("Select at least 2 funds to compare.")
    else:
        cdf = df[df['ticker'].isin(selected)].set_index('ticker')
        metrics = {
            "Price":('price','dollar'),"NAV / Share":('nav_per_share','dollar'),
            "P / NAV":('pnav','x'),"Non-Accrual % (Cost)":('na_pct_cost','pct'),
            "Non-Accrual % (FV)":('na_pct_fv','pct'),"PIK % of Income":('pik_pct','pct'),
            "Leverage":('leverage','x'),"NII / Share":('nii_per_share','dollar'),
            "Dividend / Share":('dividend_per_share','dollar'),"Div Yield":('div_yield_market','pct'),
            "NII Coverage":('nii_coverage','x'),"Wtd Avg Yield":('weighted_avg_yield','pct'),
            "Portfolio Cos":('num_portfolio_companies','num'),"Implied Recovery":('implied_recovery_rate','pct'),
            "Grade":('grade','str'),"Sentiment":('sentiment_score','sent'),"Period":('quarter','str'),
        }
        header_cols = st.columns([1.5]+[1]*len(selected))
        with header_cols[0]: st.markdown("**Metric**")
        for i,t in enumerate(selected):
            r = cdf.loc[t]; g = r['grade']
            with header_cols[i+1]:
                st.markdown(f"<div style='text-align:center;padding:8px;background:{grade_bg(g)};border-radius:8px;border:1px solid rgba(0,0,0,0.06);'><div style='font-family:Geist Mono,monospace;font-size:15px;font-weight:700;color:#0F1923;'>{t}</div><div style='font-size:11px;font-weight:600;color:{grade_color(g)};margin-top:2px;'>Grade {g}</div></div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        for ml,(cn,ft) in metrics.items():
            row_cols = st.columns([1.5]+[1]*len(selected))
            with row_cols[0]: st.markdown(f"<div style='font-size:12px;color:#7A8899;padding:6px 0;'>{ml}</div>", unsafe_allow_html=True)
            for i,t in enumerate(selected):
                r = cdf.loc[t]; v = r.get(cn)
                if ft=='str': display=str(v) if v else "N/A"
                elif ft=='sent': display=sentiment_label(v)
                elif ft=='num': display=f"{int(v)}" if v and not pd.isna(v) else "N/A"
                else: display=fmt(v,ft)
                with row_cols[i+1]:
                    st.markdown(f"<div style='text-align:center;font-family:Geist Mono,monospace;font-size:12px;font-weight:500;padding:6px 4px;color:#0F1923;border-bottom:1px solid #F0F2F5;'>{display}</div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        radar_metrics = ['na_pct_cost','pik_pct','leverage','nii_coverage','nav_per_share']
        radar_labels = ['Non-Accrual %','PIK %','Leverage','NII Coverage','NAV/Share']
        fig_r = go.Figure()
        colors_r = ['#1A6EF2','#D93025','#0E9E60','#D97706']
        for i,t in enumerate(selected):
            r = cdf.loc[t]
            vals = [float(r.get(m) or 0) for m in radar_metrics]
            maxv = [15,25,3,2,50]
            norm = [min(v/mx*10,10) for v,mx in zip(vals,maxv)]
            norm[0]=10-norm[0]; norm[1]=10-norm[1]
            fig_r.add_trace(go.Scatterpolar(r=norm+[norm[0]],theta=radar_labels+[radar_labels[0]],fill='toself',name=t,line_color=colors_r[i%len(colors_r)],opacity=0.6))
        fig_r.update_layout(polar=dict(radialaxis=dict(visible=True,range=[0,10])),height=400,margin=dict(l=40,r=40,t=40,b=40),paper_bgcolor='white',font=dict(family='Geist, sans-serif',size=12),legend=dict(orientation='h',yanchor='bottom',y=-0.1))
        st.plotly_chart(fig_r, use_container_width=True)
