import os
import io
import requests # Open Food Facts'e istek için
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import traceback
from PIL import Image
from pyzbar import pyzbar

try:
    load_dotenv()
    print(">>> .env dosyası yüklendi (varsa).")
except Exception as e:
    print(">>> .env dosyası yüklenirken hata (opsiyonel):", e)


app = Flask(__name__)
CORS(app)

OPENFOODFACTS_API_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_HEADERS = {'User-Agent': 'ReGreenApp/1.0 - https://your-website.com (Contact: your-email@example.com)'}


def get_product_info_from_off(barcode_number):
    """Verilen barkod numarasıyla Open Food Facts API'sine sorgu yapar."""
    if not barcode_number:
        return None, "Barkod numarası sağlanmadı."

    print(f">>> Open Food Facts API'sine ({barcode_number}) sorgu gönderiliyor...")
    lookup_url = OPENFOODFACTS_API_URL.format(barcode=barcode_number)
    try:
        response = requests.get(lookup_url, headers=OFF_HEADERS, timeout=15)
        print(f">>> Open Food Facts API'den yanıt alındı. Durum Kodu: {response.status_code}")
        response.raise_for_status()
        off_data = response.json()

        if off_data.get("status") == 1 and off_data.get("product"):
            print(">>> Open Food Facts'ten ürün bilgisi bulundu.")
            return off_data.get("product"), None
        else:
            error_message = off_data.get("status_verbose", "Ürün bulunamadı.")
            print(f"--- Backend Bilgi: Barkod ({barcode_number}) OFF API'de bulunamadı: {error_message}")
            return None, f"Bu barkod için ürün bilgisi bulunamadı ({error_message})"

    except requests.exceptions.Timeout: print("--- Backend Hata: Open Food Facts isteği zaman aşımına uğradı."); return None, "Ürün bilgisi alınırken zaman aşımı yaşandı."
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 404: return None, "Bu barkod için ürün bilgisi bulunamadı (API 404)."
        else: print(f"--- Backend Hata: Open Food Facts HTTP hatası: {http_err}"); return None, f"Ürün bilgisi alınırken API hatası oluştu ({response.status_code})."
    except requests.exceptions.RequestException as req_err: print(f"--- Backend Hata: Open Food Facts isteği ağ/bağlantı hatası: {req_err}"); return None, "Ürün bilgisi alınırken ağ hatası oluştu."
    except Exception as json_err: print(f"--- HATA: Open Food Facts yanıtı işlenirken sorun: {json_err}"); return None, "Ürün bilgisi API yanıtı işlenemedi."


def determine_material_from_off_data(product_data_dict):
    """Open Food Facts verisinden ambalaj materyalini tahmin eder."""
    if not product_data_dict or not isinstance(product_data_dict, dict): return 'Bilinmiyor'
    packaging_text = (product_data_dict.get('packaging_text_tr') or product_data_dict.get('packaging_text_en') or product_data_dict.get('packaging', '')).lower()
    packaging_tags = product_data_dict.get('packaging_tags', [])
    name = (product_data_dict.get('product_name_tr') or product_data_dict.get('product_name', '')).lower()
    categories_tags = product_data_dict.get('categories_tags', [])
    all_text = f"{packaging_text} {name} {' '.join(packaging_tags)} {' '.join(categories_tags)}"
    print(f">>> Materyal tahmini için metin (OFF): {all_text[:200]}...")

    if 'en:glass-bottle' in packaging_tags or 'en:glass-jar' in packaging_tags: return 'Cam'
    if 'en:pet-bottle' in packaging_tags or 'en:plastic-bottle' in packaging_tags: return 'Plastik (PET)'
    if 'en:hdpe' in packaging_tags: return 'Plastik (HDPE)'
    if 'en:ldpe' in packaging_tags: return 'Plastik (LDPE)'
    if 'en:pp' in packaging_tags or 'en:polypropylene' in packaging_tags: return 'Plastik (PP)'
    if 'en:ps' in packaging_tags or 'en:polystyrene' in packaging_tags: return 'Plastik (PS)'
    if 'en:pvc' in packaging_tags: return 'Plastik (PVC)'
    if 'en:plastic' in packaging_tags: return 'Plastik'
    if 'en:carton' in packaging_tags: return 'Karton'
    if 'en:paper' in packaging_tags: return 'Kağıt/Karton'
    if 'en:metal-can' in packaging_tags or 'en:aluminium-can' in packaging_tags or 'en:steel-can' in packaging_tags: return 'Metal'
    if 'en:aluminium' in packaging_tags: return 'Metal'

    if 'cam şişe' in all_text or 'glass bottle' in all_text: return 'Cam'
    if 'cam kavanoz' in all_text or 'glass jar' in all_text: return 'Cam'
    if 'pet şişe' in all_text or 'pet bottle' in all_text: return 'Plastik (PET)'
    if 'plastik şişe' in all_text or 'plastic bottle' in all_text: return 'Plastik'
    if 'plastik kap' in all_text or 'plastic container' in all_text: return 'Plastik'
    if 'karton kutu' in all_text or 'cardboard box' in all_text or 'tetra pak' in all_text or 'tetra brik' in all_text: return 'Karton'
    if 'kağit' in all_text or 'paper' in all_text: return 'Kağıt/Karton'
    if 'metal kutu' in all_text or 'tin can' in all_text or 'metal can' in all_text or 'teneke kutu' in name: return 'Metal'
    if 'alüminyum' in all_text or 'aluminum' in all_text: return 'Metal'
    if 'cam' in all_text or 'glass' in all_text: return 'Cam'
    if 'plastik' in all_text or 'plastic' in all_text: return 'Plastik'
    if 'karton' in all_text or 'cardboard' in all_text: return 'Karton'
    if 'metal' in all_text: return 'Metal'

    print("--- Materyal tahmini yapılamadı, Bilinmiyor olarak ayarlandı.")
    return 'Bilinmiyor'

def getWasteInfo(materialType):
    """Materyal tipine göre atık kategorisi ve detayını döndürür."""
    mat_lower = materialType.lower()
    material_key = 'Bilinmiyor'
    if 'plastik (pet)' in mat_lower: material_key = 'Plastik'
    elif 'plastik' in mat_lower: material_key = 'Plastik'
    elif 'kağit' in mat_lower or 'karton' in mat_lower: material_key = 'Kağıt/Karton'
    elif 'cam' in mat_lower: material_key = 'Cam'
    elif 'metal' in mat_lower: material_key = 'Metal'
    elif 'organik' in mat_lower: material_key = 'Organik'

    infoMap = {
        'Plastik': { 'category': 'Mavi Atık Kutusu (Geri Dönüşüm)', 'details': 'Temiz ve kuru plastikleri (şişe, kap, ambalaj) buraya atın. Yağlı veya kirli plastikleri genel çöpe atın.' },
        'Kağıt/Karton': { 'category': 'Mavi Atık Kutusu (Geri Dönüşüm)', 'details': 'Gazete, dergi, karton kutu gibi temiz kağıtları buraya atın. Islak, yağlı kağıtlar veya peçeteler geri dönüştürülemez.' },
        'Cam': { 'category': 'Yeşil Atık Kutusu (Geri Dönüşüm)', 'details': 'Sadece cam şişe ve kavanozları buraya atın. Ampul, pencere camı, ayna veya porselen atmayın.' },
        'Metal': { 'category': 'Gri Atık Kutusu (Geri Dönüşüm)', 'details': 'İçecek kutuları, konserve kutuları gibi metal ambalajları buraya atın. Piller veya elektronik atıkları buraya atmayın.' },
        'Organik': { 'category': 'Kahverengi Atık Kutusu (Kompost) veya Genel Çöp', 'details': 'Meyve/sebze artıkları, yumurta kabukları gibi organik atıklar kompost yapılabilir.' },
        'Bilinmiyor': { 'category': 'Genel Çöp (Gri/Siyah Kutu)', 'details': 'Materyal türü belirlenemedi veya geri dönüştürülemez.' }
    }
    return infoMap.get(material_key, infoMap['Bilinmiyor'])


@app.route('/analyze', methods=['POST'])
def analyze_image_and_lookup_off():
    print("\n>>> Backend: /analyze isteği alındı (POST - pyzbar + OpenFoodFacts).")
    if 'imageFile' not in request.files: return jsonify({'success': False, 'error': 'Görsel dosyası istekte bulunamadı.'}), 400
    file = request.files['imageFile']
    if file.filename == '': return jsonify({'success': False, 'error': 'Lütfen bir görsel dosyası seçin.'}), 400
    allowed_mimetypes = {'image/jpeg', 'image/png'};
    if file.mimetype not in allowed_mimetypes: return jsonify({'success': False, 'error': 'Desteklenmeyen resim türü (JPG, PNG).'}), 400

    barcode_data = None; barcode_type = None; product_info_from_api = None; off_error = None

    try:
        print(">>> Backend: Görsel pyzbar ile okunuyor...")
        image_bytes = file.read(); img = Image.open(io.BytesIO(image_bytes))
        decoded_objects = pyzbar.decode(img)
        if not decoded_objects: return jsonify({'success': False, 'error': 'Görselde okunabilir barkod bulunamadı.'}), 404
        first_barcode = decoded_objects[0]
        try: barcode_data = first_barcode.data.decode('utf-8')
        except UnicodeDecodeError: return jsonify({'success': False, 'error': 'Barkod verisi okundu ancak karakter kodlaması anlaşılamadı.'}), 400
        barcode_type = first_barcode.type
        print(f">>> Backend: pyzbar Barkod Buldu: {barcode_data}, Tür: {barcode_type}")

        if barcode_data:
            product_info_from_api, off_error = get_product_info_from_off(barcode_data)

        final_response = {
            "success": True, "barcode_data": barcode_data, "barcode_type": barcode_type,
            "product_found": bool(product_info_from_api), "api_provider": "pyzbar + Open Food Facts",
            "product_name": "-", "brand": "-", "categories": "-", "packaging_text": "-",
            "ingredients_text": "-", "ecoscore_grade": "-", "nutriscore_grade": "-", "nova_group": "-",
            "nutrient_levels": {}, "material": "Bilinmiyor", "waste_category": "Bilinmiyor",
            "recycling_info": off_error or "Ürün bilgisi alınamadı veya bulunamadı."
        }

        if product_info_from_api:
            final_response["product_name"] = product_info_from_api.get('product_name_tr') or product_info_from_api.get('product_name', 'Bilinmiyor')
            final_response["brand"] = product_info_from_api.get('brands', 'Bilinmiyor')
            final_response["categories"] = product_info_from_api.get('categories', '-')
            final_response["packaging_text"] = product_info_from_api.get('packaging_text_tr') or product_info_from_api.get('packaging_text_en') or product_info_from_api.get('packaging', '-')
            final_response["ingredients_text"] = product_info_from_api.get('ingredients_text_with_allergens_tr') or product_info_from_api.get('ingredients_text_with_allergens_en') or product_info_from_api.get('ingredients_text', '-')
            final_response["ecoscore_grade"] = product_info_from_api.get('ecoscore_grade', 'bilgi yok').upper()
            final_response["nutriscore_grade"] = product_info_from_api.get('nutriscore_grade', 'bilgi yok').upper()
            final_response["nova_group"] = str(product_info_from_api.get('nova_group', '?'))
            final_response["nutrient_levels"] = product_info_from_api.get('nutrient_levels', {})

            material = determine_material_from_off_data(product_info_from_api)
            waste_info = getWasteInfo(material)
            final_response["material"] = material
            final_response["waste_category"] = waste_info.get('category', 'Bilinmiyor')
            final_response["recycling_info"] = waste_info.get('details', 'Bu ambalaj için özel geri dönüşüm bilgisi bulunamadı.')
        elif not off_error:
             final_response["recycling_info"] = "Bu barkod için ürün bilgisi Open Food Facts veritabanında bulunamadı."

        print(">>> Backend: Sonuçlar frontend'e gönderiliyor.")
        return jsonify(final_response)

    except ImportError as imp_err:
         print(f"--- KRİTİK HATA: Gerekli kütüphane eksik: {imp_err}"); traceback.print_exc()
         error_detail = "pyzbar/Pillow";
         if "zbar" in str(imp_err).lower(): error_detail = "ZBar/pyzbar"
         elif "PIL" in str(imp_err): error_detail = "Pillow"
         return jsonify({'success': False, 'error': f'Sunucu hatası: Gerekli bir kütüphane ({error_detail}) eksik/kurulamadı.'}), 500
    except Exception as e:
        print("--- Backend Hata: Genel hata (pyzbar veya öncesi) ---"); print(f"    Hata Detayı: {e}"); traceback.print_exc()
        error_message = "Görsel işlenirken veya barkod okunurken bir hata oluştu."
        if "Unable to find zbar shared library" in str(e) or "can't load library" in str(e).lower(): error_message = "Sunucu hatası: ZBar kütüphanesi bulunamadı/yüklenemedi."
        return jsonify({'success': False, 'error': error_message, 'details': str(e)}), 500

if __name__ == '__main__':
    print(">>> Backend sunucusu (pyzbar + Open Food Facts) http://127.0.0.1:5000 adresinde başlatılıyor...")
    app.run(debug=True, port=5000, host='0.0.0.0')