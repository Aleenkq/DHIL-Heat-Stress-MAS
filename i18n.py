"""Presentation-only localization; ACL payloads and simulation codes stay unchanged."""
import re

WORDS = {
    'Your profile':'ملفك الشخصي', 'Create profile':'إنشاء الملف الشخصي',
    'Edit profile':'تعديل الملف الشخصي', 'Back':'رجوع', 'Language':'اللغة',
    'Age':'العمر', 'Sex':'الجنس', 'Male':'ذكر', 'Female':'أنثى',
    'Height (cm)':'الطول (سم)', 'Weight (kg)':'الوزن (كجم)',
    'Body mass index (BMI)':'مؤشر كتلة الجسم', 'Heart condition':'مرض في القلب',
    'Diabetes':'السكري', 'Respiratory condition':'مرض تنفسي',
    'Used to hot weather':'معتاد على الأجواء الحارة',
    'Your guide':'دليلك الشخصي', 'Monitor & Test':'المراقبة والاختبار',
    'Menu':'القائمة', 'Weather source':'مصدر الطقس', 'Live (Open-Meteo)':'مباشر (Open-Meteo)',
    'Manual':'يدوي', 'Air temperature (°C)':'درجة حرارة الهواء (°م)', 'Humidity (%)':'الرطوبة (%)',
    'Follow serious advice automatically':'اتباع التوصيات الجدية تلقائيًا',
    'Profile':'الملف الشخصي', 'LangSmith tracing':'تتبّع LangSmith',
    'Tracing enabled':'التتبّع مفعّل', 'Tracing disabled':'التتبّع غير مفعّل',
    'Tracing is configured by the team on the server.':'يضبط الفريق التتبّع من إعدادات الاستضافة.',
    'Heat-stress assistant':'مساعد الوقاية من الإجهاد الحراري',
    'Set up your profile to explore your personal guide.':'أكمل ملفك الشخصي لعرض دليلك.',
    'Academic prototype. Uses entered profile data, not body sensors. Does not provide a diagnosis or contact emergency services.':'نموذج أكاديمي يعتمد على البيانات المدخلة، وليس على حساسات جسدية. لا يقدّم تشخيصًا ولا يتصل بخدمات الطوارئ.',
    'Map of the Haram precinct':'خريطة المنطقة المحيطة بالحرم', 'Your next step':'خطوتك التالية',
    'Right now':'الطقس الآن', 'I drank water':'شربت الماء', 'I feel unwell':'أشعر بتوعّك',
    'I feel better':'أشعر بتحسّن', 'Walk to the suggested point':'المشي إلى النقطة المقترحة',
    'Rest for':'مدة الراحة', 'Start rest':'بدء الراحة', 'End rest':'إنهاء الراحة',
    'Walk 5 min':'مشي ٥ دقائق', 'Walk 30 min':'مشي ٣٠ دقيقة', 'Walk 1 hour':'مشي ساعة',
    'These buttons advance the scenario clock. During rest, they continue the rest; on a route, they move you along it.':'هذه الأزرار تقدّم وقت السيناريو؛ أثناء الراحة تكمل الراحة، وعند اتباع مسار تحرّك الحاج عليه.',
    'Water intake recorded.':'تم تسجيل شرب الماء.', 'Symptoms recorded. Follow the advice below.':'تم تسجيل الأعراض. اتبع التوصية أدناه.',
    'Recovery reported. The symptom alert remains active until the recovery conditions are met.':'تم تسجيل الإبلاغ عن التحسّن. يبقى تنبيه الأعراض حتى تتحقق شروط إنهائه.',
    'Recovery reported.':'تم تسجيل الإبلاغ عن التحسّن.', 'No suggested route yet.':'لا يوجد مسار مقترح حاليًا.',
    'Rest started. Advance the scenario clock to complete it.':'بدأت الراحة. قدّم وقت السيناريو لإكمالها.',
    'Rest completed and recorded.':'اكتملت الراحة وتم تسجيلها.',
    'Rest ended early; the minimum rest duration was not reached.':'انتهت الراحة مبكرًا ولم تكتمل المدة اللازمة لتسجيلها.',
    'Risk over time':'تغيّر مؤشر الخطر', 'Heat-stress risk':'مؤشر الإجهاد الحراري',
    'Minutes until High risk':'دقائق حتى ارتفاع الخطر', 'Minutes since water':'دقائق منذ شرب الماء',
    'Feels like (°C)':'الحرارة المحسوسة (°م)', 'Not within 2 hours':'ليس خلال ساعتين',
    'Last known readings — Health Agent is down.':'قراءات سابقة؛ وكيل الصحة متوقف.',
    'Health monitoring is unavailable: advice uses the heat level only.':'مراقبة الصحة غير متاحة؛ التوصية تعتمد على الحرارة فقط.',
    'Ask nearby staff or call a medic. This app does not contact emergency services.':'اطلب المساعدة من الموظفين القريبين أو المسعف. التطبيق لا يتصل بالطوارئ.',
    'Station service is unavailable; use nearby staff for help.':'خدمة الموارد غير متاحة؛ اطلب المساعدة من الموظفين القريبين.',
    'Walking':'يمشي', 'Resting':'يستريح', 'Arrived':'وصل', 'Ready':'جاهز',
    'Destination':'الوجهة', 'Remaining distance':'المسافة المتبقية', 'Estimated waiting time':'وقت الانتظار التقديري',
    'No destination selected':'لم تُحدّد وجهة', 'Today’s heat outlook':'توقّعات الحرارة اليوم',
    'Best hours to be outside':'الساعات الأنسب للخروج', 'Avoid walking in the sun':'تجنّب المشي تحت الشمس',
    'No comfortable hours in this forecast.':'لا توجد ساعات مريحة في هذه التوقّعات.',
    'No dangerous hours in this forecast.':'لا توجد ساعات ضمن نطاق الخطر في هذه التوقّعات.',
    'Live forecast — Open-Meteo':'توقّعات مباشرة — Open-Meteo',
    'Example forecast — live service unavailable':'توقّعات افتراضية — الخدمة المباشرة غير متاحة',
    'Map features: OpenStreetMap. Shade, capacities, waiting times, and some stations are team assumptions.':'معالم الخريطة من OpenStreetMap؛ التظليل والسعات وأوقات الانتظار وبعض المحطات افتراضية.',
    'Agents':'الوكلاء', 'Messages (ACL)':'الرسائل (ACL)', 'Failures and scenarios':'الأعطال والسيناريوهات',
    'Stations':'المحطات', 'History':'السجل', 'Performatives':'أنواع الرسائل',
    'Filter by agent, conversation or content':'ابحث بالوكيل أو المحادثة أو المحتوى', 'Rows':'عدد الصفوف',
    'Choose a scenario, then use the Walk buttons to advance its clock.':'اختر سيناريو ثم استخدم أزرار المشي لتقدّم الوقت.',
    'Heat wave (44°C)':'موجة حر (٤٤°م)', 'Health Agent failure':'تعطّل وكيل الصحة',
    'All rest points closed':'إغلاق جميع نقاط الراحة', 'Restore everything':'استعادة الجميع',
    'Agent':'الوكيل', 'Take down':'تعطيل', 'Bring back':'استعادة',
    'ML model fails (use rules)':'تعطّل النموذج (استخدام القواعد)',
    'Weather service fails (use fallback)':'تعطّل خدمة الطقس (استخدام البديل)',
    'Station':'المحطة', 'Close station':'إغلاق المحطة', 'Open station':'فتح المحطة',
    'Low':'منخفض', 'Moderate':'متوسط', 'High':'مرتفع', 'Critical':'حرج',
    'Safe':'مريح', 'Caution':'حذر', 'Extreme Caution':'حذر شديد', 'Danger':'خطر', 'Extreme Danger':'خطر شديد',
    'OK':'مستقر', 'INFO':'معلومة', 'ATTENTION':'انتباه', 'WARNING':'تحذير', 'URGENT':'عاجل', 'EMERGENCY':'طارئ',
    'LIVE':'مباشر', 'MANUAL':'يدوي', 'CACHE':'بيانات محفوظة', 'CACHED':'بيانات محفوظة', 'FALLBACK':'افتراضي',
    'heat':'وكيل الطقس', 'health':'وكيل الصحة', 'prevention':'وكيل الوقاية', 'resource':'وكيل الموارد', 'route':'وكيل المسار',
    'agent':'الوكيل', 'state':'الحالة', 'status':'التفاصيل', 'up':'يعمل', 'DOWN':'متوقف',
    'station':'المحطة', 'need':'الخدمة', 'zone':'المنطقة', 'free':'السعة المتاحة', 'wait_min':'الانتظار بالدقائق',
    'closed':'مغلق', 'source':'المصدر', 'team assumption':'افتراض الفريق',
    'minute':'الدقيقة', 'risk_score':'مؤشر الخطر', 'risk_class':'فئة الخطر', 'level':'التنبيه',
    'code':'رمز القرار', 'heat_index_c':'الحرارة المحسوسة', 'medic':'توصية بمساعدة طبية',
    'id':'المعرّف', 'step':'الخطوة', 'performative':'نوع الرسالة', 'from':'المرسل', 'to':'المستقبل',
    'conversation':'المحادثة', 'content':'المحتوى', 'delivered':'تم التسليم', 'yes':'نعم', 'NO':'لا',
    'water':'مياه', 'medical':'طبي', 'cooling':'تبريد', 'rest':'راحة',
    'Kaaba':'الكعبة', 'Pilgrim':'الحاج', 'Street map':'خريطة الشوارع', 'Satellite':'قمر صناعي',
    'open walkway':'ممر مكشوف', 'shaded walkway (proxy)':'ممر مظلل (تقديري)', 'suggested route':'المسار المقترح',
    'ASSUMED':'افتراضي', 'CLOSED':'مغلق', 'OSM (real)':'معلم من OSM',
}

ADVICE = {
    'SYMPTOMS':'أبلغت عن أعراض. توقف واطلب المساعدة الطبية. يظهر المسار المقترح إلى نقطة طبية أدناه.',
    'CRITICAL':'مؤشر الإجهاد الحراري حرج. توقف عن المشي واتجه إلى نقطة تبريد.',
    'HIGH':'مؤشر الإجهاد الحراري مرتفع. استرح في الظل واشرب الماء.',
    'EARLY':'مؤشر الخطر يرتفع. خذ قسطًا من الراحة في الظل قريبًا.',
    'WATER':'حان وقت شرب الماء.', 'MODERATE':'الخطر متوسط. اشرب بانتظام واختر الممرات المظللة.',
    'DEGRADED_DANGER':'مراقبة الصحة غير متاحة والحرارة خطرة. استرح في الظل واشرب الماء.',
    'DEGRADED_HOT':'مراقبة الصحة غير متاحة والجو حار. اشرب الماء وتجنّب الشمس المباشرة.',
    'DEGRADED':'مراقبة الصحة غير متاحة. اتبع احتياطات الحرارة العامة.',
    'OK':'مؤشر الخطر منخفض وفق البيانات المدخلة. حافظ على شرب الماء.',
}

def tr(text, lang='en'):
    if lang != 'ar' or not isinstance(text, str):
        return text
    if text in WORDS:
        return WORDS[text]
    if text.startswith('Zone '):
        return 'المنطقة ' + text[5:]
    return text

def station_name(name, lang='en'):
    if not name:
        return tr('No destination selected', lang)
    known = {
        'Ajyad_Emergency_Hospital':('Ajyad Emergency Hospital','مستشفى أجياد للطوارئ'),
        'Red_Crescent':('Red Crescent Medical Point','نقطة الهلال الأحمر الطبية'),
        'Zamzam_Filling_Point':('Zamzam Water Point','نقطة مياه زمزم'),
        'osm_8783559583':('Water Point — Zone D','نقطة مياه — المنطقة D'),
        'osm_8783651591':('Water Point — Zone A','نقطة مياه — المنطقة A'),
    }
    if name in known:
        return known[name][lang == 'ar']
    if name.startswith(('rest_', 'cool_')):
        kind, zone = name.split('_', 1)
        return (('منطقة راحة' if kind == 'rest' else 'محطة تبريد') + ' — المنطقة ' + zone
                if lang == 'ar' else ('Rest Area' if kind == 'rest' else 'Cooling Station') + ' — Zone ' + zone)
    return name.replace('_', ' ')

def frame(df, lang='en'):
    """Translate readable labels; keep ACL performatives, codes, and payloads intact for audit."""
    result = df.copy()
    for col in result.columns:
        if col in ('station',):
            result[col] = result[col].map(lambda s: station_name(s, lang) if s else '—')
        elif col in ('agent', 'state', 'need', 'zone', 'source', 'risk_class', 'level', 'delivered'):
            result[col] = result[col].map(lambda s: tr(s, lang))
    if lang == 'ar':
        result = result.rename(columns=lambda c: tr(c, lang))
    return result

def bmi(height_cm, weight_kg):
    if height_cm <= 0 or weight_kg <= 0:
        raise ValueError('Height and weight must be positive')
    return round(weight_kg / (height_cm / 100.0) ** 2, 1)
