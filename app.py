"""Mobile-first DHIL: welcome -> profile -> guide. All visitor state is session-local."""
import base64
import html
import math
import os
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
import ui_backend as ub
import tracing
from i18n import tr, station_name, frame, bmi, ADVICE

st.set_page_config(page_title='DHIL | ظِل', page_icon='🌿', layout='centered', initial_sidebar_state='collapsed')
try:
    secret_key = st.secrets.get('LANGSMITH_API_KEY')
    if secret_key and not os.environ.get('LANGSMITH_API_KEY'):
        tracing.setup(secret_key, st.secrets.get('LANGSMITH_PROJECT', 'dhil-heat-stress'))
except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
    pass
ss = st.session_state
for k,v in dict(stage='welcome',lang='en',weather_live=True,weather_temp=40,weather_rh=25,auto_follow=True).items():
    ss.setdefault(k,v)
lang = ss.lang
T = lambda s: tr(s,lang)
st.markdown('''<style>
.stApp {background:#fff;color:#143e34;}
.stMainBlockContainer {max-width:560px;padding:1.1rem 1rem 3rem;}
[data-testid="stHeader"] {background:rgba(255,255,255,.94);}
#MainMenu,footer {display:none;}
.stButton>button {min-height:48px;border-radius:14px;font-size:1rem;}
.stButton>button[kind="primary"] {background:#075744;border-color:#075744;color:white;}
[data-testid="stMetricValue"] {font-size:1.5rem;}
[data-testid="stMetric"] {background:#f3f8f5;border:1px solid #e0ebe5;border-radius:14px;padding:12px;}
.dhil-brand {text-align:center;margin:8px auto 18px;}
.dhil-brand img {width:190px;height:190px;object-fit:contain;}
.dhil-welcome {min-height:48vh;display:flex;align-items:center;justify-content:center;}
.dhil-welcome img {width:min(72vw,270px);height:280px;object-fit:contain;}
.dhil-card {border:1px solid #dce8e1;border-radius:18px;padding:18px;margin:10px 0 18px;line-height:1.8;}
[data-testid="stSidebarCollapsedControl"] svg {visibility:hidden;}
[data-testid="stSidebarCollapsedControl"] button::after {content:'☰';font-size:25px;color:#075744;position:absolute;inset:0;}
[data-testid="stExpandSidebarButton"] {position:fixed;top:10px;left:12px;z-index:1000002;background:#fff!important;border:1px solid #dce8e1!important;border-radius:12px!important;width:44px;height:44px;}
[data-testid="stExpandSidebarButton"] span {visibility:hidden;}
[data-testid="stExpandSidebarButton"]::after {content:'☰';position:absolute;font-size:25px;color:#075744;}
iframe {border-radius:18px;max-width:100%;}
@media(max-width:600px) {
 .stMainBlockContainer {padding:.7rem .85rem 2rem;}
 [data-testid="stHorizontalBlock"] {gap:.6rem;}
 [data-testid="stHorizontalBlock"]>[data-testid="stColumn"] {min-width:0!important;flex:1 1 0!important;}
 [data-testid="stMetricValue"] {font-size:1.2rem;}
 h2 {font-size:1.4rem!important;} h3 {font-size:1.15rem!important;}
}
</style>''',unsafe_allow_html=True)
if lang == 'ar':
    st.markdown('''<style>.stMainBlockContainer,[data-testid="stSidebar"] {direction:rtl;text-align:right;}
    [data-testid="stMarkdownContainer"],label {text-align:right;} input[type="number"] {direction:ltr;text-align:right;}
    [data-testid="stDataFrame"],iframe {direction:ltr;}</style>''',unsafe_allow_html=True)

def logo_uri():
    p = Path('assets/logo.png')
    return 'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode() if p.exists() else ''

def flash(kind,message):
    ss.flash = (kind,message)
    st.rerun()

def preset(name):
    ss.ses.preset(name)
    if name in ('heat_wave','rest_closed'):
        ss.weather_live,ss.weather_temp,ss.weather_rh,ss.auto_follow = False,44,15,True

if ss.stage == 'welcome':
    st.markdown(f'<div class="dhil-welcome"><img src="{logo_uri()}" alt="DHIL ظِل"/></div>',unsafe_allow_html=True)
    st.markdown('<p style="text-align:center;color:#667b71">اختر لغتك · Choose your language</p>',unsafe_allow_html=True)
    if st.button('العربية',key='choose_ar',type='primary',use_container_width=True):
        ss.lang,ss.stage = 'ar','profile';st.rerun()
    if st.button('English',key='choose_en',use_container_width=True):
        ss.lang,ss.stage = 'en','profile';st.rerun()
    st.stop()

if ss.stage == 'profile':
    st.markdown(f'<div class="dhil-brand"><img src="{logo_uri()}" alt="DHIL"/></div>',unsafe_allow_html=True)
    st.subheader(T('Your profile'))
    st.caption(T('Set up your profile to explore your personal guide.'))
    if st.button(T('Back'),key='profile_back'):
        ss.stage = 'guide' if 'ses' in ss else 'welcome';st.rerun()
    for k,v in ss.get('profile_inputs',dict(p_age=36,p_sex=0,p_height=165.0,p_weight=79.0,p_cardiac=False,p_diabetes=False,p_respiratory=False,p_acclimatized=False)).items():
        ss.setdefault(k,v)
    st.number_input(T('Age'),18,90,step=1,key='p_age')
    st.selectbox(T('Sex'),[0,1],format_func=lambda n:T('Female' if n == 0 else 'Male'),key='p_sex')
    st.number_input(T('Height (cm)'),100.0,230.0,step=1.0,key='p_height')
    st.number_input(T('Weight (kg)'),25.0,250.0,step=.5,key='p_weight')
    calculated_bmi = bmi(ss.p_height,ss.p_weight)
    st.metric(T('Body mass index (BMI)'),f'{calculated_bmi:.1f}')
    st.checkbox(T('Heart condition'),key='p_cardiac')
    st.checkbox(T('Diabetes'),key='p_diabetes')
    st.checkbox(T('Respiratory condition'),key='p_respiratory')
    st.checkbox(T('Used to hot weather'),key='p_acclimatized')
    if st.button(T('Create profile'),key='create_profile',type='primary',use_container_width=True):
        ss.profile_inputs = {k:ss[k] for k in ('p_age','p_sex','p_height','p_weight','p_cardiac','p_diabetes','p_respiratory','p_acclimatized')}
        profile = dict(age=ss.p_age,sex=ss.p_sex,bmi=calculated_bmi,has_cardiac=int(ss.p_cardiac),
                       has_diabetes=int(ss.p_diabetes),has_respiratory=int(ss.p_respiratory),acclimatized=int(ss.p_acclimatized))
        with st.spinner('جارٍ تجهيز دليلك…' if lang == 'ar' else 'Preparing your guide…'):
            ss.ses = ub.Session(profile=profile,live=ss.weather_live,temp=ss.weather_temp,rh=ss.weather_rh,auto_follow=ss.auto_follow)
        ss.stage = 'guide';st.rerun()
    st.stop()

ses,sim = ss.ses,ss.ses.sim
with st.sidebar:
    st.subheader(T('Menu'))
    view = st.radio(T('Menu'),['guide','monitor'],format_func=lambda v:T('Your guide' if v == 'guide' else 'Monitor & Test'),key='view')
    selected_lang = st.selectbox(T('Language'),['en','ar'],index=0 if lang == 'en' else 1,format_func=lambda v:'English' if v == 'en' else 'العربية')
    if selected_lang != lang:ss.lang=selected_lang;st.rerun()
    if st.button(T('Edit profile'),use_container_width=True):ss.stage='profile';st.rerun()
    with st.expander('عن التطبيق' if lang=='ar' else 'About this app'):
        st.caption(T('Academic prototype. Uses entered profile data, not body sensors. Does not provide a diagnosis or contact emergency services.'))
    st.divider()
    st.subheader(T('Weather source'))
    st.radio(T('Weather source'),[True,False],format_func=lambda v:T('Live (Open-Meteo)' if v else 'Manual'),key='weather_live')
    st.slider(T('Air temperature (°C)'),25,50,key='weather_temp',disabled=ss.weather_live)
    st.slider(T('Humidity (%)'),5,90,key='weather_rh',disabled=ss.weather_live)
    ses.set_weather(ss.weather_live,ss.weather_temp,ss.weather_rh)
    st.checkbox(T('Follow serious advice automatically'),key='auto_follow')
    sim.obey = ss.auto_follow
    if view == 'monitor':
        st.divider();st.subheader(T('LangSmith tracing'))
        st.caption(T('Tracing enabled' if tracing.enabled() else 'Tracing disabled'))
        st.caption(T('Tracing is configured by the team on the server.'))

@st.cache_data(ttl=900)
def get_outlook():return ub.forecast_next_24h()

st.markdown(f'<div class="dhil-brand"><img src="{logo_uri()}" alt="DHIL"/><h2>{T("Heat-stress assistant")}</h2></div>',unsafe_allow_html=True)
if 'flash' in ss:
    kind,msg=ss.pop('flash');getattr(st,kind)(msg)
st.subheader(T('Your next step'))
c1,c2=st.columns(2)
if c1.button(T('I drank water'),use_container_width=True):ses.action('water');flash('success',T('Water intake recorded.'))
if c2.button(T('I feel unwell'),use_container_width=True):ses.action('symptoms');flash('warning',T('Symptoms recorded. Follow the advice below.'))
c1,c2=st.columns(2)
if c1.button(T('I feel better'),use_container_width=True):
    ses.action('recovered')
    flash('warning' if sim.prevention.recovery_note else 'success',T('Recovery reported. The symptom alert remains active until the recovery conditions are met.' if sim.prevention.recovery_note else 'Recovery reported.'))
if c2.button(T('Walk to the suggested point'),use_container_width=True):
    if ses.follow():st.rerun()
    else:st.info(T('No suggested route yet.'))
rest_min=st.selectbox(T('Rest for'),[5,10,15,30,60],index=2,format_func=lambda m:f'{m} '+('دقيقة' if lang=='ar' else 'min'))
if sim.rest_left>0:
    st.info(f'يستريح — متبقّي {sim.rest_left*ub.STEP_MIN} دقيقة' if lang=='ar' else f'Resting — {sim.rest_left*ub.STEP_MIN} min left')
    if st.button(T('End rest'),use_container_width=True):
        done,counted=ses.end_rest();flash('success' if counted else 'warning',T('Rest completed and recorded.' if counted else 'Rest ended early; the minimum rest duration was not reached.'))
elif st.button(T('Start rest'),use_container_width=True):
    ses.start_rest(rest_min);flash('info',T('Rest started. Advance the scenario clock to complete it.'))
for col,label,n in zip(st.columns(3),['Walk 5 min','Walk 30 min','Walk 1 hour'],[1,6,12]):
    if col.button(T(label),use_container_width=True):ses.advance(n);st.rerun()
st.caption(T('These buttons advance the scenario clock. During rest, they continue the rest; on a route, they move you along it.'))

snap=sim.snapshot()
risk,advice=snap['risk'] or {},snap['advice']
minute=sim.t*ub.STEP_MIN
st.caption(f'وقت السيناريو: +{minute} دقيقة | {T(snap["zone"])}' if lang=='ar' else f'Scenario time: +{minute} min | {snap["zone"]}')
fg,bg=ub.LEVEL_STYLE.get(advice['level'],('#333','#f5f5f5'))
txt=ADVICE.get(advice['code'],advice['text']) if lang=='ar' else advice['text']
text_color='white' if advice['level']=='EMERGENCY' else '#173c32'
st.markdown(f'<div class="dhil-card" style="background:{bg};border-color:{fg};color:{text_color}"><b>{T(advice["level"])}</b><br>{html.escape(txt)}</div>',unsafe_allow_html=True)
if advice.get('call_medic'):st.error(T('Ask nearby staff or call a medic. This app does not contact emergency services.'))
if advice.get('note'):st.warning(T('Station service is unavailable; use nearby staff for help.') if lang=='ar' else advice['note'])
if not advice.get('health_up',True):st.warning(T('Health monitoring is unavailable: advice uses the heat level only.'))
a,b=st.columns(2)
if risk:
    a.metric(T('Heat-stress risk'),f'{T(risk.get("risk_class","—"))} ({risk.get("risk_score",0):.0f})')
    ttr=risk.get('time_to_high_min');b.metric(T('Minutes until High risk'),T('Not within 2 hours') if ttr is None else f'{ttr:.0f}')
a,b=st.columns(2)
a.metric(T('Minutes since water'),f'{risk.get("minutes_since_water",0):.0f}')
hz=snap['heat']['zones'][snap['zone']] if snap.get('heat') else None
b.metric(T('Feels like (°C)'),f'{hz["hi_c"]:.1f}' if hz else '—')
if snap['health_stale']:st.warning(T('Last known readings — Health Agent is down.'))

st.subheader(T('Map of the Haram precinct'))
station=advice.get('station')
destination=sim.prevention.directory.get(station) if station else None
distance=math.hypot(sim.pos[0]-destination[0],sim.pos[1]-destination[1]) if destination else None
arrived=distance is not None and distance<2
state='Resting' if sim.rest_left>0 else 'Walking' if sim.following else 'Arrived' if arrived else 'Ready'
st.markdown('**'+T(state)+'**')
if station:
    st.write(T('Destination')+': '+station_name(station,lang))
    if arrived:
        st.success('وصلت إلى الوجهة' if lang=='ar' else 'Arrived at destination')
        station_obj=next((s for s in sim.stations if s.name==station),None)
        if station_obj:st.caption(T('Estimated waiting time')+f': {station_obj.queue_min:g} '+('دقيقة' if lang=='ar' else 'min'))
    elif sim.following and sim.path:
        pts=[sim.pos]+list(sim.path)
        remaining=sum(math.hypot(q[0]-p[0],q[1]-p[1]) for p,q in zip(pts,pts[1:]))
        st.caption(T('Remaining distance')+f': {remaining:.0f} '+('م' if lang=='ar' else 'm'))
try:components.html(ub.build_map_html(sim,lang=lang),height=390,scrolling=False)
except Exception:st.warning('الخريطة غير متاحة حاليًا.' if lang=='ar' else 'Map temporarily unavailable.')
st.caption(T('Map features: OpenStreetMap. Shade, capacities, waiting times, and some stations are team assumptions.'))
with st.expander(T('Right now')):
    if hz:
        st.write(f'{T(hz["band"])} · {hz["temp_c"]}° · {T("Humidity (%)")}: {hz["rh"]:.0f}%')
        st.caption(T(snap['heat_mode']))
with st.expander(T('Risk over time')):
    hist=ses.history_df()
    if len(hist)>1:
        chart=hist[['minute','risk_score']].rename(columns={'minute':T('minute'),'risk_score':T('risk_score')})
        st.line_chart(chart.set_index(T('minute')),color='#08765c')
    else:st.caption('قدّم السيناريو لإضافة قراءات.' if lang=='ar' else 'Advance the scenario to add readings.')
with st.expander(T('Today’s heat outlook')):
    rows,source=get_outlook()
    import pandas as pd
    chart=pd.DataFrame({('الوقت' if lang=='ar' else 'Time'):[r['label'] for r in rows],T('Feels like (°C)'):[r['hi_c'] for r in rows]})
    st.line_chart(chart.set_index(chart.columns[0]),color='#bf9a58')
    for label,bands,empty in [('Best hours to be outside',('Safe','Caution'),'No comfortable hours in this forecast.'),('Avoid walking in the sun',('Danger','Extreme Danger'),'No dangerous hours in this forecast.')]:
        ranges=ub.band_ranges(rows,bands);st.markdown('**'+T(label)+'**')
        st.write('، '.join(f'{a} – {b}' for a,b in ranges) if ranges else T(empty))
    st.caption(T('Live forecast — Open-Meteo' if source.startswith('Open-Meteo') else 'Example forecast — live service unavailable'))

if view=='monitor':
    st.divider();st.subheader(T('Monitor & Test'))
    panel=st.selectbox(T('Monitor & Test'),['Agents','Messages (ACL)','Failures and scenarios','Stations','History'],format_func=T,key='monitor_panel')
    if panel=='Agents':st.dataframe(frame(ses.agents_df(),lang),hide_index=True,use_container_width=True)
    elif panel=='Messages (ACL)':
        perfs=st.multiselect(T('Performatives'),['INFORM','REQUEST','CFP','PROPOSE','ACCEPT','REFUSE','FAILURE'])
        text=st.text_input(T('Filter by agent, conversation or content'));limit=st.slider(T('Rows'),10,200,60)
        st.dataframe(frame(ses.messages_df(limit,perfs,text),lang),hide_index=True,use_container_width=True)
    elif panel=='Failures and scenarios':
        st.caption(T('Choose a scenario, then use the Walk buttons to advance its clock.'))
        for label,name in [('Heat wave (44°C)','heat_wave'),('Health Agent failure','health_failure'),('All rest points closed','rest_closed'),('Restore everything','restore')]:
            st.button(T(label),use_container_width=True,on_click=preset,args=(name,))
    elif panel=='Stations':st.dataframe(frame(ses.stations_df(),lang),hide_index=True,use_container_width=True)
    else:st.dataframe(frame(ses.history_df(),lang),hide_index=True,use_container_width=True)
