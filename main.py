from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import roster_engine
import json
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

class StaffItem(BaseModel):
    STAFF_ID: str
    NAME_SURNAME: str
    POSITION: Optional[str] = ""
    DEDICATED_AIRWAYS: Optional[str] = ""
    NON_AVAILABLE_DAYS: Optional[str] = ""
    SPECIAL_OFF: Optional[str] = ""
    LICENSED_FOR_VEHICLE: Optional[str] = "NO"
    PREFERRED_SHIFT: Optional[str] = ""
    SERVICE_ROUTE: Optional[str] = "General"  # Örn: Halkalı, Avcılar, E-5
class PlanItem(BaseModel):
    AIRWAYS: str
    SHIFT_START: str
    SHIFT_END: str
    MONDAY: int = 0
    TUESDAY: int = 0
    WEDNESDAY: int = 0
    THURSDAY: int = 0
    FRIDAY: int = 0
    SATURDAY: int = 0
    SUNDAY: int = 0

# --- GÜNCELLENEN KISIM ---
class RosterRequest(BaseModel):
    staff_list: List[StaffItem]
    plan_list: List[PlanItem]
    previous_week_shifts: Optional[List[Any]] = [] # YENİ: Geçmiş veri alanı
    mentor_pairing: Optional[Dict[str, str]] = None
    settings: Optional[dict] = None
    shared_shift_groups: Optional[List[List[str]]] = []
    rotation_requests: Optional[List[Dict[str, str]]] = None
    scenario_leaves: Optional[List[Dict[str, Any]]] = None
    

@app.post("/generate-roster")
def generate_roster(request: RosterRequest):
    print(f"İstek Geldi! Personel: {len(request.staff_list)}, Görev: {len(request.plan_list)}")
    # BURAYA EKLEYİN:
    print(f"📥 GELEN ROTASYON İSTEĞİ: {request.rotation_requests}") 

    print(f"İstek Geldi! Personel: {len(request.staff_list)}, Görev: {len(request.plan_list)}")
    
    # Geçmiş verisi geldi mi kontrol et
    if request.previous_week_shifts:
        print(f"📅 Geçmiş Hafta Verisi Mevcut: {len(request.previous_week_shifts)} kayıt")
    else:
        print("ℹ️ Geçmiş hafta verisi yok (İlk hafta olabilir)")

    try:
        staff_data = [item.dict() for item in request.staff_list]
        plan_data = [item.dict() for item in request.plan_list]
        prev_data = request.previous_week_shifts 
        
        
        # Motoru 3 parametreyle çalıştır
        result = roster_engine.run_engine(staff_data, plan_data, prev_data,request.mentor_pairing, settings=request.settings,shared_shift_groups=request.shared_shift_groups, rotation_requests=request.rotation_requests,scenario_leaves=request.scenario_leaves )
        
        if result is None:
            raise HTTPException(status_code=400, detail="Çözüm Bulunamadı (Kurallar çok sıkı).")
        
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
# main.py içine ekle:

@app.delete("/clear-all-shifts")
def clear_all_shifts():
    try:
        # Eğer verileri bir dosyada (json) tutuyorsan, içi boş bir liste ile üzerine yaz.
        # Eğer veriler sadece bellekte (global değişken) ise onları sıfırla.
        
        # Örnek: Eğer JSON dosyası kullanıyorsan:
        import json
        with open("shifts.json", "w") as f:
            json.dump([], f)
            
        with open("rosters.json", "w") as f:
            json.dump([], f)
            
        print("🧹 TÜM VERİLER TEMİZLENDİ!")
        return {"status": "success", "message": "Tüm vardiya geçmişi silindi."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # main.py dosyasına ekle

import json
import os # Dosya işlemlerini yapmak için

SHIFTS_FILE = "shifts.json"
ROSTERS_FILE = "rosters.json"

@app.delete("/clear-week-roster/{week_id}")
def clear_week_roster(week_id: str):
    """Belirtilen hafta ID'sine ait tüm vardiyaları ve rosterları siler."""
    try:
        # 1. Shifts (Vardiyalar) dosyasını temizle
        if os.path.exists(SHIFTS_FILE):
            with open(SHIFTS_FILE, "r") as f:
                shifts = json.load(f)
            
            # Silinmeyecek vardiyaları filtrele
            filtered_shifts = [shift for shift in shifts if shift.get('weekId') != week_id]
            
            with open(SHIFTS_FILE, "w") as f:
                json.dump(filtered_shifts, f, indent=4)
            
            print(f"🧹 Shifts: {week_id} haftasına ait {len(shifts) - len(filtered_shifts)} adet vardiya silindi.")
        
        # 2. Rosters (Onaylanmış Rosterlar) dosyasını temizle (Sadece yedek için)
        if os.path.exists(ROSTERS_FILE):
            with open(ROSTERS_FILE, "r") as f:
                rosters = json.load(f)
            
            # Silinmeyecek rosterları filtrele
            filtered_rosters = [roster for roster in rosters if roster.get('weekId') != week_id]
            
            with open(ROSTERS_FILE, "w") as f:
                json.dump(filtered_rosters, f, indent=4)
                
            print(f"🧹 Rosters: {week_id} haftasına ait {len(rosters) - len(filtered_rosters)} adet roster silindi.")
        
        return {"status": "success", "message": f"{week_id} haftasına ait veriler temizlendi."}
        
    except Exception as e:
        print(f"HATA: Haftalık silme başarısız: {e}")
        raise HTTPException(status_code=500, detail=f"Haftalık veri silme hatası: {str(e)}")

# NOT: main.py dosyasının en üstüne 'import json' ve 'import os' eklediğinizden emin olun.