# -*- coding: utf-8 -*-
"""
tools_generate_new_icons.py — Genera le icone con Tag Blu Grande e Puro Testo ("Browser" e "PDF") + Banana piccola in basso a destra
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

def generate_icons():
    base_dir = Path(__file__).resolve().parent
    orig_banana_path = base_dir / "cita_icona.png"
    if not orig_banana_path.exists():
        orig_banana_path = base_dir / "assets" / "cita_icona.png"
    
    orig_banana = Image.open(orig_banana_path).convert("RGBA")

    # Font
    try:
        font_pdf = ImageFont.truetype("segoeuib.ttf", 140)
    except Exception:
        try:
            font_pdf = ImageFont.truetype("arialbd.ttf", 140)
        except Exception:
            font_pdf = ImageFont.load_default()

    try:
        font_browser = ImageFont.truetype("segoeuib.ttf", 86)
    except Exception:
        try:
            font_browser = ImageFont.truetype("arialbd.ttf", 86)
        except Exception:
            font_browser = ImageFont.load_default()

    def create_tag_icon(text, font, is_pdf=False):
        img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        
        # 1. Ombra soffusa del Tag Blu
        shadow_layer = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        draw_shadow = ImageDraw.Draw(shadow_layer)
        draw_shadow.rounded_rectangle([36, 44, 476, 468], radius=56, fill=(0, 0, 0, 70))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(10))
        img.paste(shadow_layer, (0, 0), shadow_layer)

        draw = ImageDraw.Draw(img)

        # 2. Tag Blu Principale (cITA Blue #005CA8) con bordo elegante
        tag_box = [32, 40, 480, 460]
        draw.rounded_rectangle(tag_box, radius=56, fill=(0, 92, 168, 255), outline=(0, 140, 240, 255), width=6)

        # Barra superiore / dettaglio stile tag con leggero riflesso
        draw.rounded_rectangle([38, 46, 474, 110], radius=50, fill=(255, 255, 255, 30))
        draw.rectangle([38, 70, 474, 110], fill=(255, 255, 255, 30))

        # 3. Puro Testo in grande ("Browser" o "PDF")
        # Calcola coordinate di centraggio
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # Posiziona il testo (leggermente spostato verso l'alto a sinistra per lasciare spazio alla banana)
        if is_pdf:
            text_x = int((512 - text_w) / 2) - 20
            text_y = int((460 - text_h) / 2) - 10
        else:
            text_x = int((512 - text_w) / 2) - 20
            text_y = int((460 - text_h) / 2) - 25

        # Ombra leggera del testo per massima leggibilità
        draw.text((text_x + 3, text_y + 3), text, font=font, fill=(0, 45, 90, 200))
        # Testo Bianco Puro
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))

        # 4. Banana piccola in primo piano in basso a destra
        banana_size = 200
        banana_small = orig_banana.resize((banana_size, banana_size), Image.Resampling.LANCZOS)
        
        banana_x = 512 - banana_size - 10
        banana_y = 512 - banana_size - 10

        # Ombra sotto la banana
        banana_shadow = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        b_shadow_draw = ImageDraw.Draw(banana_shadow)
        b_shadow_draw.ellipse([banana_x + 10, banana_y + 10, banana_x + banana_size + 10, banana_y + banana_size + 10], fill=(0, 0, 0, 80))
        banana_shadow = banana_shadow.filter(ImageFilter.GaussianBlur(8))
        img.paste(banana_shadow, (0, 0), banana_shadow)

        # Incolla la Banana in primo piano
        img.paste(banana_small, (banana_x, banana_y), banana_small)

        return img

    # Genera Icone
    browser_img = create_tag_icon("Browser", font_browser, is_pdf=False)
    pdf_img = create_tag_icon("PDF", font_pdf, is_pdf=True)

    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

    # Salva Browser
    browser_img.save(base_dir / "cita_icona.png", "PNG")
    browser_img.save(base_dir / "cita_icona.ico", format="ICO", sizes=icon_sizes)
    if (base_dir / "assets").exists():
        browser_img.save(base_dir / "assets" / "cita_icona.png", "PNG")
        browser_img.save(base_dir / "assets" / "cita_icona.ico", format="ICO", sizes=icon_sizes)

    # Salva PDF
    pdf_img.save(base_dir / "cita_pdf.png", "PNG")
    pdf_img.save(base_dir / "cita_pdf.ico", format="ICO", sizes=icon_sizes)
    if (base_dir / "assets").exists():
        pdf_img.save(base_dir / "assets" / "cita_pdf.png", "PNG")
        pdf_img.save(base_dir / "assets" / "cita_pdf.ico", format="ICO", sizes=icon_sizes)

    print("ALL_ICONS_GENERATED_CORRECTLY")

if __name__ == "__main__":
    generate_icons()
