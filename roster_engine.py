# -*- coding: utf-8 -*-
# DOSYA ADI: roster_engine.py
# AÇIKLAMA: Yüklenen 'roster.py' dosyasının birebir motor halidir.

import pandas as pd
from collections import defaultdict
from ortools.sat.python import cp_model
import random


# roster_engine.py içindeki process_previous_shifts fonksiyonunu tamamen bununla değiştir:

def process_previous_shifts(shift_list, staff_list):
    print(f"\n--- GEÇMİŞ VERİ DETAYLI ANALİZİ ({len(shift_list)} Kayıt) ---")
    if not shift_list: return {}
    
    df_prev = pd.DataFrame(shift_list)
    
    # Sütun isimlerini normalize et (Bazen 'shiftType' bazen 'shift' gelebilir)
    if 'shiftType' not in df_prev.columns and 'shift' in df_prev.columns:
        df_prev['shiftType'] = df_prev['shift']
        
    staff_ids = [str(s['STAFF_ID']) for s in staff_list]
    prev_data = {}
    
    # Geriye doğru kontrol edilecek günler
    REVERSE_DAYS = ["Sunday", "Saturday", "Friday", "Thursday", "Wednesday", "Tuesday", "Monday"]
    # Türkçe gün isimleri gelirse diye eşleşme haritası
    DAY_MAP = {
        "PAZAR": "Sunday", "CUMARTESI": "Saturday", "CUMA": "Friday", 
        "PERSEMBE": "Thursday", "CARSAMBA": "Wednesday", "SALI": "Tuesday", "PAZARTESI": "Monday",
        "SUNDAY": "Sunday", "SATURDAY": "Saturday", "FRIDAY": "Friday", 
        "THURSDAY": "Thursday", "WEDNESDAY": "Wednesday", "TUESDAY": "Tuesday", "MONDAY": "Monday"
    }

    for p_id in staff_ids:
        # Sadece bu personelin kayıtlarını al
        p_shifts = df_prev[df_prev['employeeId'].astype(str) == p_id].copy()
        
        sunday_shift_type = "OFF"
        streak_count = 0
        
        if not p_shifts.empty:
            # Gün isimlerini standart hale getir
            p_shifts['norm_day'] = p_shifts['day'].apply(lambda x: DAY_MAP.get(str(x).upper(), str(x)))
            
            # 1. Pazar Durumunu Bul (Mevcut mantık)
            p_sunday = p_shifts[p_shifts['norm_day'] == "Sunday"]
            if not p_sunday.empty and str(p_sunday.iloc[0].get('shiftType', 'off')).lower() != 'off':
                raw_time = str(p_sunday.iloc[0].get('startTime', ''))
                s_mm = mm(raw_time)
                if s_mm >= 1320 or s_mm < 240: sunday_shift_type = "N"
                elif s_mm >= 840: sunday_shift_type = "E"
                else: sunday_shift_type = "M"
            
            # 2. Streak (Zincirleme Çalışma) Hesapla - YENİ KISIM
            # Pazar'dan geriye doğru git. OFF gördüğün an dur.
            for day_name in REVERSE_DAYS: # Hata olmaması için yukarıdaki REVERSE_DAYS listesini kullanacağız
                day_record = p_shifts[p_shifts['norm_day'] == day_name]
                
                # Kayıt yoksa veya 'off' ise zincir koptu demektir
                if day_record.empty:
                    break
                    
                s_type = str(day_record.iloc[0].get('shiftType', 'off')).lower()
                if s_type == 'off':
                    break
                
                # Çalışmış sayılır
                streak_count += 1
        
        prev_data[p_id] = {
            "sunday_shift": sunday_shift_type,
            "streak": streak_count # Örn: Pazar, Cmt, Cuma çalıştıysa streak=3
        }
        
    return prev_data

# =========================================================================
# === SABİTLER (roster.py dosyanızdan alındı) ===
# =========================================================================
# Bu listeler orijinal kodunuzdaki gibidir

VS_KOORDINE_GROUP = ["VS", "KOORDİNE"]
SHEET = "Roster"

DAYS = ["MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"]
DAY_IDX = {"MONDAY":0,"TUESDAY":1,"WEDNESDAY":2,"THURSDAY":3,"FRIDAY":4,"SATURDAY":5,"SUNDAY":6}

# =========================================================================
# === YARDIMCI FONKSİYONLAR ===
# =========================================================================
def norm(s): return str(s).strip().upper() if pd.notna(s) else ""
def split_list(v):
    v = norm(v)
    if v in ("", "NONE"): return []
    return [x.strip() for x in v.split(",")]

def mm(hhmm):
    try:
        h, m = hhmm.split(":")
        return int(h)*60 + int(m)
    except: return 0

def shift_window(start, end):
    s = mm(start); e = mm(end)
    if e <= s: e += 24*60 
    return s, e

# Vardiya Grupları (roster.py'deki orijinal mantık)
def shift_group(start, end):
    # M_START, M_END = shift_window("08:00","17:00") vb. tanımlar fonksiyon içinde tekrar hesaplanıyor
    # Ancak burada direkt saat mantığını kullanıyoruz
    s = start
    # Orijinal kodunuzda shift_group fonksiyonunun davranışı:
    M_START, M_END   = shift_window("08:00","17:00")
    E_START, E_END   = shift_window("14:00","00:30")
    N_START, N_END   = shift_window("23:59","08:30")
    AC_START, AC_END = shift_window("04:30","14:30")
    
    if s==M_START and end==M_END: return "M"
    if s==E_START and end==E_END: return "E"
    if s==N_START and end==N_END: return "N"
    if s==AC_START and end==AC_END: return "M" # AT CARGO sabah sayılır
    
    # Eğer tam eşleşme yoksa genel aralık kontrolü (Web'den gelen veri için güvenlik)
    if s >= 1320 or s < 240: return "N" 
    elif s >= 840: return "E"
    else: return "M"

def primary_pref(position_tag, tags):
    tags = list(tags)
    if "HAVUZ" in tags: return {"HAVUZ"}
    if position_tag in tags: return {position_tag}
    for t in tags:
        if t not in ("HAVUZ","GECE"): return {t}
    return {tags[0]} if tags else set()

def format_minutes_to_h_mm(total_minutes):
    if total_minutes <= 0: return "00:00"
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

# =========================================================================
# === MOTOR FONKSİYONU (DÜZELTİLMİŞ) ===
# =========================================================================
def run_engine(staff_data, plan_data, prev_data, mentor_pairing=None, settings=None, shared_shift_groups=None, rotation_requests=None, scenario_leaves=None):
    print(f"--- Motor Çalışıyor: {len(staff_data)} Personel, {len(plan_data)} Görev ---")

# DOĞRUSU BU: Önce parametreden gelen veriyi değişkene ata
    previous_shifts_list = prev_data 

    df = pd.DataFrame(plan_data)
    staff_df = pd.DataFrame(staff_data)

    # Sonra bu değişken dolu mu boş mu diye kontrol et
    if previous_shifts_list:
        # Gelen listeyi, motorun anlayacağı sözlük yapısına çeviriyoruz
        previous_roster_data = process_previous_shifts(previous_shifts_list, staff_data)
    else:
        previous_roster_data = {}

    # 1. VERİ HAZIRLIK
    staff = pd.DataFrame(staff_data)
    plan = pd.DataFrame(plan_data)
    
    # 1. VERİYİ PANDAS'A ÇEVİR
    staff = pd.DataFrame(staff_data)
    plan = pd.DataFrame(plan_data)

    # --- YENİ EKLENEN SENARYO MANTIĞI BAŞLANGIÇ ---
    if scenario_leaves:
        print(f"\n🧪 SENARYO MODU AKTİF: {len(scenario_leaves)} kişi için test izni uygulanıyor...")
        
        for leave in scenario_leaves:
            s_id = str(leave.get('employeeId')) # Frontend'den gelen ID
            days_list = leave.get('days', [])   # ['Monday', 'Tuesday'] gibi liste
            
            # Bu ID'ye sahip personeli bul
            mask = staff['STAFF_ID'] == s_id
            
            if mask.any():
                # Mevcut kapalı günlerini al (Varsa)
                current_off = str(staff.loc[mask, 'NON_AVAILABLE_DAYS'].iloc[0])
                if current_off == "nan" or current_off == "None": current_off = ""
                
                # Yeni günleri string olarak hazırla (virgülle birleştir)
                new_days_str = ",".join(days_list).upper()
                
                # Eskilerle yenileri birleştir
                if current_off:
                    final_off_str = f"{current_off},{new_days_str}"
                else:
                    final_off_str = new_days_str
                
                # DataFrame'i güncelle
                staff.loc[mask, 'NON_AVAILABLE_DAYS'] = final_off_str
                
                # İzin türüne göre 'SPECIAL_OFF' olarak da işaretleyebiliriz (opsiyonel ama daha garantidir)
                staff.loc[mask, 'SPECIAL_OFF'] = final_off_str
                
                print(f"   -> {s_id} için günler kapatıldı: {days_list}")
            else:
                print(f"   ⚠️ Uyarı: Senaryodaki {s_id} ID'li personel listede bulunamadı.")
    # --- YENİ EKLENEN SENARYO MANTIĞI BİTİŞ ---

    # Veri Normalizasyonu
    for df in (staff, plan):
        for c in df.columns:
            if df[c].dtype == object: df[c] = df[c].apply(norm)

    # Sütun kontrolleri ve hazırlık
    if "DEDICATED_AIRWAYS" not in staff.columns: staff["DEDICATED_AIRWAYS"] = ""
    if "SPECIAL_OFF" not in staff.columns: staff["SPECIAL_OFF"] = ""
    if "NON_AVAILABLE_DAYS" not in staff.columns: staff["NON_AVAILABLE_DAYS"] = ""
    if "PREFERRED_SHIFT" not in staff.columns: staff["PREFERRED_SHIFT"] = ""
    if "POSITION" not in staff.columns: staff["POSITION"] = ""

    staff["TAGS"] = staff["DEDICATED_AIRWAYS"].apply(split_list)

# ---------------------------------------------------------
    # 5. ROTASYON MANTIĞI (Tüm kuralları ezer)
    # ---------------------------------------------------------
    if rotation_requests:
        print(f"\n🔄 ROTASYON: {len(rotation_requests)} kişi işleniyor...")
        
        for req in rotation_requests:
            r_staff_id = str(req.get('staff_id', ''))
            r_department = str(req.get('department', '')).strip().upper()
            
            # Bu personeli bul
            mask = staff_df['STAFF_ID'] == r_staff_id
            
            if mask.any():
                # 1. Vardiyayı sabitle
                staff_df.loc[mask, 'PREFERRED_SHIFT'] = '08:00-17:00'
                
                # 2. Off günlerini sabitle (Cumartesi, Pazar)
                # (Sistem dilin İngilizce ise 'Saturday,Sunday', Türkçe ise ona göre ayarla)
                staff_df.loc[mask, 'NON_AVAILABLE_DAYS'] = 'Saturday,Sunday'
                staff_df.loc[mask, 'SPECIAL_OFF'] = '' # Özel izinleri temizle ki çakışmasın
                
                # 3. Departman Ataması (Dedicated Airways'i değiştiriyoruz)
                # Kişi artık sadece bu departmana (Havayoluna) hizmet eder.
                staff_df.loc[mask, 'DEDICATED_AIRWAYS'] = r_department
                
                # İpucu: Eğer bu departman plan_list'te yoksa (talep yoksa), 
                # motor kişiyi atayamaz. O yüzden plan tablosunda bu departman için 
                # sembolik de olsa bir sütun/talep olduğundan emin olmalısın.
                
                print(f"   -> Personel {r_staff_id} rotasyona alındı: {r_department}, 08:00-17:00, Haftasonu Off.")
    # ---------------------------------------------------------
    # ---------------------------------------------------------
    # 🕵️ GELİŞMİŞ DİL ÇEVİRİCİ (DEBUG MODU)
    # ---------------------------------------------------------
    def parse_days_tr_to_en_debug(row, col_name):
        # Veriyi hücreden al
        val = row.get(col_name, "")
        p_name = row.get("NAME_SURNAME", "Bilinmiyor")
        
        # Sadece HAKAN ÇELEBİ için log basalım ki sorunu görelim
        is_target = "HAKAN" in str(p_name).upper()
        
        if pd.isna(val) or val == "" or val == "[]":
            if is_target: print(f"🛑 {p_name} -> {col_name} BOŞ GELDİ!")
            return []
            
        # String değilse string yap
        val_str = str(val).upper()
        
        if is_target: 
            print(f"📥 {p_name} -> {col_name} GELEN HAM VERİ: '{val_str}'")

        # Temizlik (Köşeli parantezleri ve tırnakları temizle - Bazen JSON array string gelir)
        val_str = val_str.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
        
        # Norm fonksiyonunu bypass edip manuel map yapıyoruz (Garanti olsun)
        # Türkçe karakter sorunlarını (İ/I, Ş/S) yok sayarak mapliyoruz.
        
        raw_list = [x.strip() for x in val_str.split(",")]
        final_list = []
        
        # HARİTA (Genişletilmiş - Hem Türkçe Hem İngilizce Hem Bozuk Karakter)
        TR_MAP = {
            "PAZARTESI": "MONDAY", "PZT": "MONDAY", "MONDAY": "MONDAY",
            "SALI": "TUESDAY", "SAL": "TUESDAY", "TUESDAY": "TUESDAY",
            "CARSAMBA": "WEDNESDAY", "ÇARŞAMBA": "WEDNESDAY", "CARS": "WEDNESDAY", "WEDNESDAY": "WEDNESDAY",
            "PERSEMBE": "THURSDAY", "PERŞEMBE": "THURSDAY", "PRS": "THURSDAY", "THURSDAY": "THURSDAY",
            "CUMA": "FRIDAY", "CUM": "FRIDAY", "FRIDAY": "FRIDAY",
            "CUMARTESI": "SATURDAY", "CUMARTESİ": "SATURDAY", "CMT": "SATURDAY", "SATURDAY": "SATURDAY",
            "PAZAR": "SUNDAY", "PZR": "SUNDAY", "SUNDAY": "SUNDAY"
        }
        
        for item in raw_list:
            # Standartlaştır: İ -> I, Ş -> S, Ğ -> G, Ü -> U, Ö -> O, Ç -> C
            clean_item = item.replace("İ", "I").replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
            
            if clean_item in TR_MAP:
                final_list.append(TR_MAP[clean_item])
            else:
                if is_target: print(f"   ⚠️ TANIMSIZ GÜN: '{item}' (Temiz hali: '{clean_item}') haritada yok!")

        if is_target:
            print(f"✅ {p_name} -> {col_name} SONUÇ: {final_list}")

        return final_list

    # Fonksiyonu satır satır uygula (axis=1)
    staff["OFF_DAYS"] = staff.apply(lambda row: parse_days_tr_to_en_debug(row, "NON_AVAILABLE_DAYS"), axis=1)
    staff["SPECIAL_OFF_DAYS"] = staff.apply(lambda row: parse_days_tr_to_en_debug(row, "SPECIAL_OFF"), axis=1)
    # ---------------------------------------------------------
    
    airway_priority = {}
    for p, s in staff.iterrows():
        ranks = {}
        tags = s["TAGS"]
        
        # KURAL: Eğer personelin yeteneklerinde 'HAVUZ' varsa;
        if "HAVUZ" in tags:
            # HAVUZ'a en yüksek önceliği (0 maliyet) ver
            ranks["HAVUZ"] = 0
            # Diğer tüm yeteneklerini (SV, KU vs.) ikinci plana (Maliyet 1) at
            for t in tags:
                if t != "HAVUZ":
                    ranks[t] = 1
        else:
            # HAVUZ yapamıyorsa, listedeki normal sırasına göre öncelik ver
            for idx, tag in enumerate(tags):
                ranks[tag] = idx
                
        airway_priority[p] = ranks

   # ---------------------------------------------------------
    # 🌍 DİL ÇEVİRİCİ (TR -> EN) - OFF GÜNLERİ İÇİN
    # ---------------------------------------------------------
    def parse_off_days_tr_to_en(val):
        # 1. Önce standart temizlik (Büyük harf, boşluk silme)
        if not val or pd.isna(val): return []
        val = norm(val) # Senin norm fonksiyonun (İ->I, Ç->C yapıyor)
        
        if val == "ALL DAY": return []
        
        raw_list = [x.strip() for x in val.split(",")]
        final_list = []
        
        # 2. Çeviri Haritası (Normalized TR -> EN)
        # Senin 'norm' fonksiyonun Türkçe karakterleri İngilizceye çevirdiği için 
        # haritayı ona göre hazırlıyoruz (Örn: ÇARŞAMBA -> CARSAMBA)
        TR_MAP = {
            "PAZARTESI": "MONDAY", "PZT": "MONDAY",
            "SALI": "TUESDAY", "SAL": "TUESDAY",
            "CARSAMBA": "WEDNESDAY", "CRS": "WEDNESDAY", "WEDNESDAY": "WEDNESDAY",
            "PERSEMBE": "THURSDAY", "PRS": "THURSDAY", "THURSDAY": "THURSDAY",
            "CUMA": "FRIDAY", "CUM": "FRIDAY", "FRIDAY": "FRIDAY",
            "CUMARTESI": "SATURDAY", "CMT": "SATURDAY", "SATURDAY": "SATURDAY",
            "PAZAR": "SUNDAY", "PZR": "SUNDAY", "SUNDAY": "SUNDAY"
        }
        
        for item in raw_list:
            # Önce haritada var mı bak
            if item in TR_MAP:
                final_list.append(TR_MAP[item])
            # Belki zaten İngilizce gelmiştir (MONDAY)
            elif item in ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]:
                final_list.append(item)
            # Hiçbiri değilse logla (Debug için)
            else:
                print(f"⚠️ Tanımsız Gün: {item}")
                
        return final_list

    # Fonksiyonu uygula
    staff["OFF_DAYS"] = staff["NON_AVAILABLE_DAYS"].apply(parse_off_days_tr_to_en)
    # ---------------------------------------------------------
    # --- YENİ EKLENEN KISIM BAŞLANGIÇ ---
    def check_is_morning(val):
        if not isinstance(val, str): # Boşsa geç
            return 0
        val = str(val).strip().upper()
        # Eğer saat 07, 08 veya 09 ile başlıyorsa (Örn: 08:00-17:00) SABAHÇI say
        if val.startswith("07:") or val.startswith("08:") or val.startswith("09:"):
            return 1
        # Eski usul MORNING yazan varsa onu da kabul et
        if val == "MORNING":
            return 1
        return 0

    staff["PREF_MORNING"] = staff["PREFERRED_SHIFT"].apply(check_is_morning)
    # --- YENİ EKLENEN KISIM BİTİŞ ---
    staff["LICENSED"]     = (staff["LICENSED_FOR_VEHICLE"]=="YES").astype(int)
    staff["POSITION_TAG"] = staff["POSITION"].apply(lambda s: norm(s).split(",")[0] if pd.notna(s) else "")
    # --- GÖREVLERİ OLUŞTUR ---
    tasks = []
    task_counter = 0
    
    # Plan verisinde 'AIRWAYS' sütununu arıyoruz
    airway_col = "AIRWAYS" if "AIRWAYS" in plan.columns else "AIRWAY"

    for idx, r in plan.iterrows():
        airway_tag = r.get(airway_col, "GENEL")
        is_hard_constraint = bool(r.get("IS_HARD", False))
        start_str, end_str = r["SHIFT_START"], r["SHIFT_END"]
        s0, e0 = shift_window(start_str, end_str)
        grp = shift_group(s0, e0)
        
        for day_idx, day in enumerate(DAYS):
            req = r.get(day)
            if pd.notna(req) and int(req) > 0:
                tasks.append({
                    "task_id": f"T{task_counter}",
                    "is_hard": is_hard_constraint,
                    "row": idx,
                    "day": day,
                    "day_idx": day_idx,
                    "tag": airway_tag,
                    "start": s0, "end": e0,
                    "req": int(req),
                    "grp": grp,
                    "start_str": start_str, "end_str": end_str
                })
                task_counter += 1

    tasks_by_day = defaultdict(list)
    for t in tasks: tasks_by_day[t["day"]].append(t)

    # --- UYGUNLUK FİLTRESİ (Excel Kodundaki Mantıkla Aynı) ---
    eligible = {}
    pref_primary = {}
    for p, s in staff.iterrows():
        pref_primary[p] = primary_pref(s["POSITION_TAG"], s["TAGS"])

    for t in tasks:
        cand = []
        for p, s in staff.iterrows():
            # Normal OFF + SPECIAL_OFF
            all_off_days = set(s["OFF_DAYS"]) | set(s["SPECIAL_OFF_DAYS"])
            if t["day"] in all_off_days:
                continue

            # Dedicated Airways (HARD)
            # (Orijinal kodda: if t["tag"] not in s["TAGS"]: continue vardı.
            # Ancak HAVUZ görevlerinde esneklik için şu kontrolü ekliyoruz)
            if t["tag"] != "HAVUZ" and t["tag"] not in s["TAGS"]:
                 continue
            
            # MORNING tercihi HARD (Orijinal kodda vardı)
            # Bu satır, sabah tercih edenleri diğer vardiyalardan men eder.
            if s["PREF_MORNING"]==1 and t["grp"] != "M":
                continue
            
            cand.append(p)
        eligible[t["task_id"]] = cand

    # =================================================================
    # 3. CP-SAT MODEL KURULUMU
    # =================================================================
    m = cp_model.CpModel()
    x = {} 
    for t in tasks:
        for p in eligible[t["task_id"]]:
            x[(p, t["task_id"])] = m.NewBoolVar(f"x_p{p}_{t['task_id']}")

# 3.1 Plan Satırları (HAVUZ MANTIĞI TEMİZLENDİ)
    understaff_terms = []
    understaff_terms = []
    overstaff_terms = []
    N_START_VAL, _ = shift_window("23:59","08:30") 

    for t in tasks:
        assigned_vars = [x[(p, t["task_id"])] for p in eligible[t["task_id"]]]

        # Eksiklik değişkeni (Mevcut)
        under = m.NewIntVar(0, t["req"], f"under_{t['task_id']}")
        understaff_terms.append(under)
        
        # --- YENİ: Fazlalık Değişkeni ---
        # Atanan kişi sayısı talepten fazlaysa burası artar
        over = m.NewIntVar(0, len(staff), f"over_{t['task_id']}")
        overstaff_terms.append(over)

        # Denklem: Atananlar + Under - Over == Demand
        # Bu denklem sayesinde sistem hem eksiği hem fazlayı takip eder
        m.Add(sum(assigned_vars) + under - over == t["req"])
        
        # Partner/Grup Desteği (VS/KOORDINE) - Artık doğrudan bununla başlıyoruz
        if t["tag"] in VS_KOORDINE_GROUP:
            sibling_tasks = [st for st in tasks if st["day"] == t["day"] and st["grp"] == t["grp"] and st["tag"] in VS_KOORDINE_GROUP and st["tag"] != t["tag"]]
            for st in sibling_tasks:
                assigned_vars.extend([x[(p, st["task_id"])] for p in eligible[st["task_id"]]])

# Eksiklik ve Fazlalık değişkenleri
        under = m.NewIntVar(0, t["req"], f"under_{t['task_id']}")
        over = m.NewIntVar(0, len(staff), f"over_{t['task_id']}")
        
        understaff_terms.append(under)
        overstaff_terms.append(over)

# ==========================================================
    # 🧠 AKILLI ÖNCELİKLENDİRME (DİNAMİK NADİRLİK)
    # ==========================================================
    task_priority_scores = {}
    for t in tasks:
        # Bu işi yapabilecek toplam personel sayısı
        num_candidates = len(eligible[t["task_id"]])
        
        if num_candidates == 0:
            score = 0
        elif num_candidates == 1:
            # Sadece 1 uzman varsa, bu görevi doldurmak hayati önem taşır
            score = 5000000 
        elif num_candidates == 2:
            score = 1000000
        elif num_candidates <= 5:
            # Alternatif azsa hala çok değerli
            score = 100000
        else:
            # Herkes yapabiliyorsa (GECE/VS gibi), önceliği düşük tut
            score = 100
            
        task_priority_scores[t["task_id"]] = score

    # 3.2 Çakışma Yasağı
    for day, ts in tasks_by_day.items():
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                ti, tj = ts[i], ts[j]
                overlap = not (ti["end"] <= tj["start"] or tj["end"] <= ti["start"])
                if overlap:
                    common = set(eligible[ti["task_id"]]) & set(eligible[tj["task_id"]])
                    for p in common:
                        m.Add(x[(p, ti["task_id"])] + x[(p, tj["task_id"])] <= 1)

    # 3.3 Yardımcı Değişkenler (y: vardiya tipi, z: çalışma günü)
    y = {(p,d,g): m.NewBoolVar(f"y_p{p}_{d}_{g}") for p in staff.index for d in DAYS for g in ("M","E","N")}
    z = {(p,d):   m.NewBoolVar(f"z_p{p}_{d}")     for p in staff.index for d in DAYS}

    for p in staff.index:
        for d in DAYS:
            for g in ("M","E","N"):
                rel = [t for t in tasks_by_day[d] if t["grp"] == g and (p in eligible[t["task_id"]])]
                if rel:
                    m.Add(y[(p,d,g)] >= sum(x[(p,t["task_id"])] for t in rel) ) # En az bir görev varsa 1 olsun (Basitleştirilmiş)
                    # Doğrusu: sum(x) >= y ve y <= sum(x) ama 0/1 için >= yeterli değil, <= lazım.
                    # Orijinal koddaki mantık:
                    # m.Add(y[(p,d,g)] >= x[(p,t["task_id"])]) for t in rel
                    # m.Add(y[(p,d,g)] <= sum(x[(p,t["task_id"])] for t in rel))
                    for t in rel:
                        m.Add(y[(p,d,g)] >= x[(p,t["task_id"])])
                    m.Add(y[(p,d,g)] <= sum(x[(p,t["task_id"])] for t in rel))
                else:
                    m.Add(y[(p,d,g)] == 0)
            
            m.Add(sum(y[(p,d,g)] for g in ("M","E","N")) <= 1)
            m.Add(z[(p,d)] == sum(y[(p,d,g)] for g in ("M","E","N")))

    # 3.4 Ertesi Gün Kuralları
    for p in staff.index:
        for i in range(6):
            d, dn = DAYS[i], DAYS[i+1]
            m.Add(y[(p,dn,"M")] == 0).OnlyEnforceIf(y[(p,d,"E")])
            m.Add(y[(p,dn,"M")] == 0).OnlyEnforceIf(y[(p,d,"N")])
            m.Add(y[(p,dn,"E")] == 0).OnlyEnforceIf(y[(p,d,"N")])

    # 3.5 Haftalık Çalışma Günü Sayısı
    for p, s in staff.iterrows():
        extra = len(set(s["SPECIAL_OFF_DAYS"]))
        work_days = 5 - extra
        if work_days < 0: work_days = 0
        m.Add(sum(z[(p,d)] for d in DAYS) == work_days) # KATI KURAL

    # 3.6 Haftalık En Fazla 3 Gece
    for p in staff.index:
        limit = 3
        # Geçmiş veriye göre limit düşürme
        if p in previous_roster_data and previous_roster_data[p]["sunday_shift"] == "N":
             limit = 2
        m.Add(sum(y[(p,d,"N")] for d in DAYS) <= limit)

    # 3.7 Lisanslı Araç (Gece)
    for day, ts in tasks_by_day.items():
        gece_tasks = [t for t in ts if t["tag"]=="GECE" and t["start"]==N_START_VAL]
        arac_night = [t for t in ts if t["tag"]=="ARAÇ" and t["start"]==N_START_VAL]
        if not arac_night: continue

        any_licensed = m.NewBoolVar(f"AnyLicensedNight_{day}")
        lic_assigns = []
        for gt in gece_tasks:
            for p in eligible[gt["task_id"]]:
                if staff.loc[p,"LICENSED"] == 1:
                    lic_assigns.append(x[(p, gt["task_id"])])

        if lic_assigns:
            m.Add(sum(lic_assigns) >= 1).OnlyEnforceIf(any_licensed)
            m.Add(sum(lic_assigns) == 0).OnlyEnforceIf(any_licensed.Not())
        else:
            m.Add(any_licensed == 0)

        need = m.NewIntVar(0,1,f"ARAÇNightNeed_{day}")
        m.Add(need + any_licensed == 1)
        acc = []
        for at in arac_night:
            for p in eligible[at["task_id"]]:
                acc.append(x[(p, at["task_id"])])
        if acc:
            m.Add(sum(acc) == need)

    # 3.8 OFF Günlerini Dağıtma (Scatter)
    off = {}
    off_scatter_terms = []
    for p in staff.index:
        for d in DAYS:
            b = m.NewBoolVar(f"off_p{p}_{d}")
            off[(p, d)] = b
            m.Add(b == z[(p, d)].Not())

    for p in staff.index:
        for i in range(len(DAYS)):
            for j in range(i+2, len(DAYS)):
                bi = m.NewBoolVar(f"both_off_p{p}_{i}_{j}")
                # bi = 1 if (off[i] AND off[j])
                m.AddBoolAnd([off[(p, DAYS[i])], off[(p, DAYS[j])]]).OnlyEnforceIf(bi)
                off_scatter_terms.append(bi)

  # -------------------------------------------------------------------------
    # 3.9 KISITLAMA KONTROLÜ (GÜNCELLENDİ)
    # -------------------------------------------------------------------------
    print("\n--- 🛑 KISITLAMA KONTROLÜ BAŞLIYOR 🛑 ---")
    
    for p in staff.index:
        p_real_id = str(staff.loc[p, "STAFF_ID"])
        
        # Geçmiş verileri çek
        streak = 0
        sunday_status = "OFF"
        
        if p_real_id in previous_roster_data:
            prev = previous_roster_data[p_real_id]
            sunday_status = prev.get("sunday_shift", "OFF")
            streak = prev.get("streak", 0) # Yeni hesaplanan streak
        
        # === KURAL 1: 7. GÜN ZORUNLU OFF (YASAL SINIR) ===
        if streak > 0:
            # Yasal sınır 6 gün çalışmadır. 7. gün OFF olmalı.
            days_until_forced_off = 6 - streak
            
            if days_until_forced_off < 0:
                # Zaten 6 günden fazla çalışmış, Pazartesi kesinlikle OFF olmalı
                m.Add(z[(p, "MONDAY")] == 0)
                print(f"   ⚠️ {p_real_id} geçen haftadan {streak} gün çalışarak geldi -> Pazartesi ZORUNLU OFF.")
            
            elif days_until_forced_off < 7:
                # Bu hafta içinde bir gün sınıra takılacak.
                # Örnek: Streak=5. days_until=1 (Sadece Pazartesi çalışabilir).
                # Pazartesi(0) ve Salı(1) çalışırsa toplam 7 gün olur. YASAK.
                # Yani: z[0] + ... + z[limit] <= limit olmalı (Hepsi 1 olamaz).
                
                limit_idx = days_until_forced_off
                
                # Bu aralıktaki günlerin toplamı, gün sayısından az olmalı (En az 1 tane OFF girmeli)
                range_vars = [z[(p, DAYS[i])] for i in range(limit_idx + 1)]
                m.Add(sum(range_vars) <= limit_idx)
                
                print(f"   ⚡ {p_real_id} {streak} gün streak ile geldi. {DAYS[limit_idx]} gününe kadar en az 1 OFF verilmeli.")

        # === KURAL 2: MEVCUT PAZAR GECE/AKŞAM KISITLAMASI ===
        if sunday_status in ("E", "N"):
            if "MONDAY" in tasks_by_day:
                for t in tasks_by_day["MONDAY"]:
                    if t["start"] < 840: # 14:00 öncesi
                        if p in eligible[t["task_id"]]:
                            m.Add(x[(p, t["task_id"])] == 0)

        # === KURAL 3: MEVCUT GECE DÖNÜŞÜ OFF ===
        if sunday_status == "N":
             m.Add(z[(p, "MONDAY")] == 0)
             
    print("--- 🛑 KISITLAMA KONTROLÜ BİTTİ 🛑 ---\n")

    # =================================================================
    # 4. AMAÇ FONKSİYONU (GÜNCELLENMİŞ VE BİRLEŞTİRİLMİŞ)
    # =================================================================
    
    # 1. Vardiya ve Görev Tercihleri Hesaplaması
    weighted_mismatch = []
    airway_pref = []
    noise = []
    shift_pref_penalty = [] # YENİ: Vardiya Saati Tercihi (Morning/Afternoon)

    for t in tasks:
        for p in eligible[t["task_id"]]:
            # A. Pozisyon/Havuz Uyumsuzluğu
            if t["tag"] not in pref_primary[p]:
                weighted_mismatch.append(random.randint(1, 10) * x[(p, t["task_id"])])

            # B. Dedicated Airway Önceliği
            rank = airway_priority[p].get(t["tag"], 100)
            airway_pref.append(rank * x[(p, t["task_id"])])

            # C. Gürültü (Çözüm çeşitliliği için)
            if random.randint(0, 3) > 0:
                noise.append(x[(p, t["task_id"])])
            
            # -----------------------------------------------------------------
            # D. YENİ: VARDİYA SAATİ TERCİHİ (AKILLI SAAT OKUYUCU)
            # -----------------------------------------------------------------
            # Personelin tercihini al (Örn: "14:00-00:30" veya "MORNING")
            pref = str(staff.loc[p, "PREFERRED_SHIFT"]).strip().upper()
            
            is_mismatch = False
            
            # 1. SAAT FORMATI KONTROLÜ (Örn: "14:00-00:30")
            if "-" in pref and ":" in pref:
                # İstenen başlangıç saatini çek: "14:00"
                wanted_start = pref.split("-")[0].strip()[:5]
                # Görevin başlangıç saatini çek: "14:00"
                task_start = str(t["start_str"]).strip()[:5]
                
                # Eğer saatler tutmuyorsa, bu bir UYUMSUZLUKTUR.
                if wanted_start != task_start:
                    is_mismatch = True
            
            # 2. ESKİ USÜL KELİME KONTROLÜ (Yedek)
            elif pref == "AFTERNOON" and t["grp"] != "E": is_mismatch = True
            elif pref == "NIGHT" and t["grp"] != "N": is_mismatch = True
            elif pref == "MORNING" and t["grp"] != "M": is_mismatch = True 
            
            # CEZA UYGULAMA
            if is_mismatch:
                # Eğer personel bu göreve atanırsa (x=1), sisteme 50.000 ceza puanı yaz.
                # Bu sayı ne kadar büyük olursa, sistem o kişiyi o kadar zorunlu o saate yazar.
                shift_pref_penalty.append(50000 * x[(p, t["task_id"])])
            # -----------------------------------------------------------------

    # 2. Çalışma Tercihi (TEMBELLİĞİ ÖNLEME - Ali Fuat Fix)
    work_preference_penalty = []
    for p in staff.index:
        for d in DAYS:
            # Çalışılmayan (z=0) her gün için ceza puanı (1) ekle
            work_preference_penalty.append(z[(p,d)].Not())

    # 3. Gece Bloklama (Gece -> Ertesi Gün OFF olursa ceza)
    night_block_penalty = []
    for p in staff.index:
        for i in range(len(DAYS)):
            d_curr, d_next = DAYS[i], DAYS[(i + 1) % len(DAYS)]
            p_night_off = m.NewBoolVar(f"no_{p}_{i}")
            m.AddBoolAnd([y[(p, d_curr, "N")], z[(p, d_next)].Not()]).OnlyEnforceIf(p_night_off)
            night_block_penalty.append(p_night_off)

  # -------------------------------------------------------------------------
    # 3.3.5 ZORUNLU 2 GÜN OFF KURALI (GECE VARDİYASI SONRASI)
    # -------------------------------------------------------------------------

    # 1. Yardımcı Değişken Tanımı: Bu kişi hiç Gece çalıştı mı?
    has_night = {}
    for p in staff.index:
        h = m.NewBoolVar(f"has_night_p{p}")
        has_night[p] = h
        # En az bir gece varsa h=1
        m.Add(sum(y[(p,d,"N")] for d in DAYS) >= 1).OnlyEnforceIf(h)
        m.Add(sum(y[(p,d,"N")] for d in DAYS) == 0).OnlyEnforceIf(h.Not())

    # 2. Yardımcı Değişken Tanımı: Bu kişinin 2 gün üst üste OFF'u var mı?
    has_2_off = {}
    for p in staff.index:
        t_2off = m.NewBoolVar(f"has_2_off_p{p}")
        has_2_off[p] = t_2off
        
        # 2-OFF çiftlerini bul
        off_pairs = []
        for i in range(len(DAYS)):
            d1, d2 = DAYS[i], DAYS[(i+1) % len(DAYS)] # Haftalık döngü (Pazar-Pazartesi bağlantısı dahil)
            
            # OFF değişkenleri: z.Not() -> 1 (OFF), 0 (Çalışıyor)
            off_d1 = z[(p, d1)].Not()
            off_d2 = z[(p, d2)].Not()
            
            pair = m.NewBoolVar(f"pair_{p}_{i}")
            # pair = 1 IFF (off_d1 AND off_d2)
            m.AddBoolAnd([off_d1, off_d2]).OnlyEnforceIf(pair)
            off_pairs.append(pair)

        # Toplam OFF çifti sayısı en az 1 ise (yani bir yerde 2 OFF varsa), has_2_off = 1
        m.Add(sum(off_pairs) >= 1).OnlyEnforceIf(t_2off)
        m.Add(sum(off_pairs) == 0).OnlyEnforceIf(t_2off.Not())


    # 3. ZORUNLU KURAL (HARD CONSTRAINT)
    # KURAL: Eğer Gece çalıştıysa (has_night=1), ZORUNLU 2 gün OFF yapmalı (has_2_off=1).
    for p in staff.index:
        m.Add(has_2_off[p] == 1).OnlyEnforceIf(has_night[p])
        
        # Debug amaçlı: Kuralı uyguladığımızı konsola yazalım
        m.AddHint(has_2_off[p], 1) # Solvere bu kurala uymayı teşvik et

# -------------------------------------------------------------------------
    # 3.4.1 HAFTALIK 45 SAAT SINIRI KISITLAMASI (SOFT)
    # -------------------------------------------------------------------------
    MAX_MINUTES = 45 * 60  # 2700 dakika (45 saat)

    total_mins = {}
    overflow_mins = {}
    
    for p in staff.index:
        
        # 1. Total Çalışma Dakikasını Hesapla (Net süre)
        assigned_durations = []
        for t in tasks:
            if p in eligible[t["task_id"]]:
                duration_mins = t["end"] - t["start"]
                if duration_mins < 0: duration_mins += 24*60 
                
                # Molayı düşerek net süreyi alıyoruz (Net süre = Süre - 60dk Mola)
                net_duration = max(0, duration_mins - 60)
                
                assigned_durations.append(net_duration * x[(p, t["task_id"])])

        t_mins = m.NewIntVar(0, 7 * 24 * 60, f"TotalMins_p{p}") # Haftalık maksimum dakika
        m.Add(t_mins == sum(assigned_durations))
        total_mins[p] = t_mins
        
        # 2. Taşma Dakikasını (Overflow) Hesapla
        # OverflowMins = Çalışma Süresi - 2700 (Eğer sonuç pozitifse)
        o_mins = m.NewIntVar(0, 7 * 24 * 60, f"OverflowMins_p{p}")
        
        # Kural: TotalMins <= MAX_MINUTES + OverflowMins (Overflow'un en küçük olması hedeflenir)
        m.Add(t_mins <= MAX_MINUTES + o_mins)
        
        overflow_mins[p] = o_mins
    # -------------------------------------------------------------------------
    # 3.3.6 SOFT KURAL DEĞİŞKENİ: 2 OFF Alınamadıysa Ceza
    # -------------------------------------------------------------------------

    no_2_off_penalty_terms = []
    
    # has_2_off = 1 ise (başarılı), ceza = 0
    # has_2_off = 0 ise (başarısız), ceza = 1
    for p in staff.index:
        # has_2_off değişkenini tersine çeviriyoruz (z.Not() gibi)
        # Bu, has_2_off[p] değişkeninin zorunlu olarak 0'a eşit olması durumunu yaratır.
        p_no_off = m.NewBoolVar(f"p_no_2_off_{p}")
        
        # p_no_off (Ceza) = 1 IFF has_2_off[p] = 0
        m.Add(p_no_off + has_2_off[p] == 1)
        
        no_2_off_penalty_terms.append(p_no_off)

# --- DİNAMİK ÖNCELİKLENDİRME ÖDÜLLERİ ---
    dynamic_priority_bonus = []
    for t in tasks:
        for p in eligible[t["task_id"]]:
            # Eğer p personeli t görevine atanırsa (x[(p,t)] == 1 olur), 
            # o görevin nadirlik puanını (task_priority_scores) ödül olarak listeye ekle.
            score = task_priority_scores.get(t["task_id"], 0)
            dynamic_priority_bonus.append(score * x[(p, t["task_id"])])

    # =================================================================
    # MINIMIZE (AĞIRLIKLAR VE ÖNCELİKLER)
    # =================================================================
    m.Minimize(
        # 1. MUTLAK GEREKSİNİMLER (En Yüksek)
        100000 * sum(understaff_terms) +
        800000 * sum(overstaff_terms) + # <--- BURASI: 14:00 boşken 08:00'e 2. kişiyi yazmasını engeller
        80000 * sum(overflow_mins.values()) -   # <-- YENİ EKLENDİ: 45 Saat Üstü Ceza   
    
        
        # 2. ÇALIŞMA ZORUNLULUĞU (Ali Fuat'ı Ofiste Tutma)
        11000 * sum(work_preference_penalty) +   # <-- 11.000 PUAN (Çok Önemli)

        # 3. YÜKSEK ÖNCELİKLİ TERCİHLER
        10000  * sum(airway_pref) +              # Dedicated Airway
        5000 * sum(shift_pref_penalty) +         # Vardiya Saati Tercihi
        
        # 4. ÇALIŞAN SAĞLIĞI (Orta)
        1000 * sum(no_2_off_penalty_terms) +     # <-- YENİ EKLENDİ: 2 Gün OFF Teşviki (SOFT KURAL)
        50 * sum(night_block_penalty) +          
        
        # 5. DİĞERLERİ (Düşük)
        10 * sum(weighted_mismatch) +             
        3  * sum(off_scatter_terms) +             
        1  * sum(noise)                         
    )
# ---------------------------------------------------------
    # 🤝 MENTOR - MENTEE (KANKA) MODU (HARD CONSTRAINT)
    # ---------------------------------------------------------
    if mentor_pairing and "mentor_id" in mentor_pairing and "mentee_id" in mentor_pairing:
        
        m_id = str(mentor_pairing["mentor_id"])
        s_id = str(mentor_pairing["mentee_id"])
        
        print(f"\n--- 🔗 MENTOR MODU AKTİF: {m_id} ile {s_id} birbirine bağlanıyor ---")
        
        # DataFrame indexlerini bul (Pandas indexi lazım, ID yetmez)
        # NOT: Senin staff datanda ID sütunu 'STAFF_ID' veya 'id' olabilir. İkisini de kontrol et.
        # Genelde senin kodunda 'STAFF_ID' kullanıyoruz.
        
        idx_mentor = staff.index[staff['STAFF_ID'].astype(str) == m_id].tolist()
        idx_mentee = staff.index[staff['STAFF_ID'].astype(str) == s_id].tolist()
        
        if idx_mentor and idx_mentee:
            p1 = idx_mentor[0] # Mentorun tablodaki sıra numarası (Örn: 5. satır)
            p2 = idx_mentee[0] # Menteenin tablodaki sıra numarası (Örn: 12. satır)
            
            p1_name = staff.loc[p1, "NAME_SURNAME"]
            p2_name = staff.loc[p2, "NAME_SURNAME"]
            
            print(f"   ✅ Eşleşme Başarılı: {p1_name} <==> {p2_name}")
            
            # KURAL: Haftanın her günü, vardiya türleri (M, E, N) birbirine EŞİT olmalı.
            # y[(p, d, "M")] değişkeni 1 ise (Sabahçı), diğerininki de 1 olmalı.
            # Hepsi 0 ise (OFF), diğerininki de 0 olmalı.
            
            for d in DAYS:
                for grp in ["M", "E", "N"]:
                    # Mentor neyse, Mentee o olsun (Matematiksel Eşitlik)
                    m.Add(y[(p1, d, grp)] == y[(p2, d, grp)])
            
            print("   🔒 Kural Eklendi: Vardiyalar ve OFF günleri kilitlendi.")
            
        else:
            print(f"   ⚠️ HATA: ID'ler bulunamadı. Mentor: {m_id}, Mentee: {s_id}")
            # ID uyuşmazlığı varsa (Frontend '1' yolluyor, Backend '001' bekliyorsa) burada uyarı verir.
    # ---------------------------------------------------------
    # =================================================================
    # 5. ÇÖZÜM
    # =================================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 180
    res = solver.Solve(m)
    
    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None

    # =================================================================
    # 6. ÇIKTI OLUŞTURMA (HAVUZ PARTNERS TEMİZLENDİ)
    # =================================================================
    assign_by_pt = defaultdict(list)
    unassigned_tasks_by_day = defaultdict(list)
    summary_stats = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # --- ADIM 1: GÖREVLERİ DAĞIT VE İSTATİSTİKLERİ TOPLA ---
    for t in tasks:
        assigned_count = 0
        for p in eligible[t["task_id"]]:
            if solver.Value(x[(p,t["task_id"])]) == 1:
                assign_by_pt[(p, t["day"])].append(t)
                assigned_count += 1
        
        # Kapsama Mantığı (VS/KOORDINE/ARAÇ)
        total_coverage = assigned_count
        
        # HAVUZ bloğu buradan kaldırıldı. İlk kontrol VS_KOORDINE ile başlıyor:
        if t["tag"] in VS_KOORDINE_GROUP:
            sibs = [s for s in tasks if s["day"]==t["day"] and s["grp"]==t["grp"] and s["tag"] in VS_KOORDINE_GROUP and s["tag"]!=t["tag"]]
            for s in sibs:
                for p in eligible[s["task_id"]]:
                    if solver.Value(x[(p,s["task_id"])])==1: total_coverage += 1
        
        elif t["tag"] == "ARAÇ" and t["start"] == N_START_VAL:
             gtasks = [g for g in tasks if g["day"]==t["day"] and g["tag"]=="GECE" and g["start"]==N_START_VAL]
             for g in gtasks:
                for p in eligible[g["task_id"]]:
                    if solver.Value(x[(p,g["task_id"])])==1 and staff.loc[p,"LICENSED"]==1:
                        total_coverage += 1

        if assigned_count > 0:
            summary_stats[t['day']][f"{t['start_str']} - {t['end_str']}"][t['tag']] += assigned_count
        
        # Eksiklik Hesabı (Kırmızı Uyarı)
        if t["req"] > total_coverage:
            missing_val = t["req"] - total_coverage
            print(f"⚠️ EKSİK: {t['day']} {t['tag']} -> İst: {t['req']}, Var: {total_coverage}")
            unassigned_tasks_by_day[t["day"]].append({
                "day": t["day"],
                "airway": t["tag"],
                "shift_time": f"({t['start_str']} - {t['end_str']})",
                "missing": missing_val,
                "required": t["req"]
            })

    # --- ADIM 2: PERSONEL SATIRLARINI (ROWS) OLUŞTUR ---
    rows = []
    for p, s in staff.iterrows():
        row = {
            "STAFF_ID": str(s["STAFF_ID"]), 
            "NAME_SURNAME": s["NAME_SURNAME"].upper()
        }
        
        total_mins = 0
        for d in DAYS:
            cells = assign_by_pt.get((p,d), [])
            if not cells: 
                row[d] = "DAY OFF"
            else:
                parts = []
                for t in cells:
                    mn = t["end"] - t["start"]
                    if mn < 0: mn += 24*60
                    total_mins += max(0, mn - 60)
                    # +HAVUZ etiketi kaldırıldı, sadece tag yazılıyor
                    parts.append(f"{t['tag']} ({t['start_str']}-{t['end_str']})")
                row[d] = " / ".join(parts)
        
        row["NET_WORKING_HOURS"] = format_minutes_to_h_mm(total_mins)
        rows.append(row)

    # --- ADIM 3: EKSİKLERİ VE İSTATİSTİKLERİ DÜZENLE ---
    flat_unassigned = []
    for day_list in unassigned_tasks_by_day.values():
        flat_unassigned.extend(day_list)

    stats_clean = {}
    for day, times in summary_stats.items():
        stats_clean[day] = {}
        for time, tags in times.items():
            stats_clean[day][time] = dict(tags)

    # --- ADIM 4: ROTASYON UYGULA ---
    if rotation_requests:
        print(f"\n🔄 ROTASYON MODU DEVREDE (İstek Sayısı: {len(rotation_requests)})")

        for req in rotation_requests:
            req_id_raw = req.get('staff_id') or req.get('id')
            r_id = str(req_id_raw).strip()
            r_dept = str(req.get('department', 'GENEL')).strip().upper()
            
            target_shift_text = f"{r_dept} (08:00-17:00)"
            found_in_roster = False

            # Mevcut listede (rows) bu kişi var mı diye ara
            for row in rows:
                if str(row.get('STAFF_ID', '')).strip() == r_id:
                    row["MONDAY"] = target_shift_text
                    row["TUESDAY"] = target_shift_text
                    row["WEDNESDAY"] = target_shift_text
                    row["THURSDAY"] = target_shift_text
                    row["FRIDAY"] = target_shift_text
                    row["SATURDAY"] = "OFF"
                    row["SUNDAY"] = "OFF"
                    found_in_roster = True
                    break 
            
            # Eğer listede yoksa ekle
            if not found_in_roster:
                person_row = staff[staff['STAFF_ID'].astype(str) == r_id]
                
                if not person_row.empty:
                    p_name = person_row.iloc[0].get('NAME_SURNAME', 'Bilinmeyen')
                else:
                    p_name = f"Personel {r_id}"

                new_row = {
                    "STAFF_ID": r_id,
                    "NAME_SURNAME": p_name,
                    "MONDAY": target_shift_text,
                    "TUESDAY": target_shift_text,
                    "WEDNESDAY": target_shift_text,
                    "THURSDAY": target_shift_text,
                    "FRIDAY": target_shift_text,
                    "SATURDAY": "OFF",
                    "SUNDAY": "OFF"
                }
                rows.append(new_row)

    # --- ADIM 5: SONUÇLARI DÖNDÜR ---
    return {
        "status": "success",
        "roster": rows,
        "unassigned": flat_unassigned,
        "statistics": stats_clean
    }