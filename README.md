# Recap → Myanmar (+ Splitter)

**English၊ တရုတ်၊ ဟိန္ဒီ၊ ကိုရီးယား … ဘယ်ဘာသာနဲ့ ပြောထားတဲ့ recap / ဇာတ်လမ်းပြော video ကိုမဆို မြန်မာအသံနဲ့ ပြန်ထုတ်ပေးတဲ့ Windows tool**
Narrator only · Whisper + Gemini · Microsoft Edge TTS (Myanmar) · Smart Sync
**Splitter** tab — ရှည်တဲ့ video ကို မိနစ်အလိုက် အပိုင်းခွဲ (Ratio + blur နောက်ခံ၊ စာ၊ Part နံပါတ်)

> English: turns a recap/story video narrated in English, Chinese, Hindi, Korean … (detected by itself)
> into the same video narrated in Myanmar (Burmese). The Myanmar voice leads, and the picture of every
> line is re-timed to it ("Smart Sync"). A second tab, **Splitter**, cuts long videos into parts.
> See the [English section](#english) below.

---

## ဘာလုပ်ပေးလဲ

1. **နားထောင်** — video ထဲက အသံကို စက်ထဲမှာပဲ Whisper နဲ့ စာသားပြောင်းတယ်။ စကားလုံးတိုင်းရဲ့ အချိန်ကို ယူထားတယ်။
   - **Source language** = Auto-detect ဆိုရင် Whisper က ဘယ်ဘာသာလဲ အရင် နားထောင်ကြည့်တယ် (ပထမ ၈ မိနစ်)။ ကိုယ်တိုင်လည်း ရွေးလို့ရတယ်။
   - English ဆို `small.en` (~460 MB)၊ တခြားဘာသာဆို `medium` (~1.5 GB, multilingual) နဲ့ နားထောင်တယ်။ Model တွေကို ပထမဆုံးအကြိမ်ပဲ download လုပ်ရတယ်။
   - ဟိန္ဒီနဲ့ Urdu က အသံတူလို့ Auto-detect မှာ Urdu ထွက်ရင် ဟိန္ဒီအဖြစ် ရေးတယ်။
2. **အပိုင်းခွဲ** — စာကြောင်း၊ အပိုဒ်၊ အသံရပ်တဲ့နေရာတွေမှာ ခွဲပြီး အပိုင်းတိုင်းကို ၄.၂ စက္ကန့်လောက် (အများဆုံး ၅.၆ စက္ကန့်) ထားတယ်။ အပိုင်းများလေ ရုပ်နဲ့ အသံ ပိုကိုက်လေပါ။
3. **ဇာတ်လမ်း မှတ်ဉာဏ်** — Gemini က ဇာတ်လမ်းတစ်ခုလုံးကို အရင်ဖတ်ပြီး ဇာတ်ကောင်နာမည်၊ ဆက်နွယ်မှု၊ နေရာတွေကို မှတ်ထားတယ်။ ဒါကြောင့် နာမည်တွေ တစ်ပုဒ်လုံး တစ်မျိုးတည်း ဖြစ်တယ်။
4. **ဘာသာပြန်** — Gemini က တစ်ခါမှာ အပိုင်း ၄၀ စီ မြန်မာလို ပြန်တယ်။
   - ဇာတ်ကြောင်းပြောသူလို သဘာဝကျတဲ့ စကားပြောပုံစံနဲ့ ပြန်တယ်။
   - အကျဉ်းမချုပ်ဘူး၊ ချန်မထားဘူး။ အပိုင်းတစ်ခုရဲ့ အကြောင်းအရာကို ဘေးအပိုင်းထဲ မရွှေ့ဘူး။
   - ပြန်ပြီးတိုင်း စစ်ဆေးတဲ့အဆင့် (audit) က ချန်ခဲ့တာ၊ နေရာလွဲတာ၊ ထပ်နေတာတွေကို ပြန်ပြင်တယ်။
   - မြန်မာစာလုံးထဲ တခြားဘာသာ စာလုံး ညှပ်ဝင်လာရင် (ဥပမာ "ဧည့်ခန်း" နေရာမှာ "မისခန်း") Gemini ကို ပြန်မေးတယ်။
5. **အသံထုတ်** — Edge TTS မြန်မာအသံ (Thiha ယောက်ျားသံ / Nilar မိန်းမသံ) နဲ့ ထုတ်တယ်။ "Short pauses" ဖွင့်ထားရင် Edge ထည့်တတ်တဲ့ အသံတိတ်ကို ဖြတ်လို့ စာကြောင်းကြားမှာ ~၀.၂၅ စက္ကန့်ပဲ နားတယ်။
6. **Smart Sync** — မြန်မာအသံက အချိန်ကို ဦးဆောင်ပြီး ရုပ်က လိုက်ညှိတယ်။ အသေးစိတ်ကို [Smart Sync ဘယ်လိုအလုပ်လုပ်လဲ](#smart-sync-ဘယ်လိုအလုပ်လုပ်လဲ) မှာ ကြည့်ပါ။
7. **စာတန်းထိုး** — မူရင်း transcript စာသားကို မြန်မာအသံရဲ့ အချိန်နဲ့ကိုက်အောင် မြင်ရတဲ့ video ပုံရိပ်အတွင်းမှာ တိုက်ရိုက်ထည့်ပေးတယ်။
8. **ဖြည့်စွက်** — Blur box (မူရင်း watermark/စာတန်းဖုံးဖို့)၊ Title၊ Logo၊ Extra text၊ Zoom၊ Flip တွေကို preview ပေါ်မှာ နေရာချပြီး ထည့်လို့ရတယ်။ Video အချိုး (**16:9 / 9:16 / 1:1 / Original**) ကိုလည်း ရွေးလို့ရတယ်။

ထွက်လာတဲ့ video မှာ **မြန်မာအသံပဲ** ပါတယ်။ မူရင်း English အသံနဲ့ နောက်ခံသီချင်း မပါဘူး။

## လိုအပ်တာ

| | |
|---|---|
| Windows | 10 / 11 (64-bit) |
| Python | **3.12, 64-bit** — [python.org](https://www.python.org/downloads/) ကနေ သွင်းပါ။ "Add python.exe to PATH" နဲ့ "tcl/tk" ကို အမှန်ခြစ်ပါ |
| FFmpeg | `ffmpeg.exe` + `ffprobe.exe` — မရှိရင် `INSTALL_REQUIREMENTS.bat` က အလိုလို download လုပ်ပေးတယ် ([gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/)) |
| Gemini API key | အခမဲ့ ရတယ် — [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| Internet | Gemini နဲ့ Edge TTS အတွက် |
| NVIDIA GPU | မဖြစ်မနေ မလိုဘူး။ ရှိရင် Whisper နဲ့ video render ပိုမြန်တယ် (NVENC)။ မရှိရင် CPU နဲ့ အလိုလို လုပ်တယ် |

## ထည့်သွင်းနည်း (တစ်ခါပဲ လုပ်ရ)

1. ဒီ repo ကို download လုပ်ပါ (**Code → Download ZIP** ပြီးရင် ဖြည်ပါ၊ သို့မဟုတ် `git clone`)။
2. Python 3.12 ကို သွင်းပါ (အပေါ်က ဇယားကို ကြည့်ပါ)။
3. **`INSTALL_REQUIREMENTS.bat`** ကို double-click နှိပ်ပါ။ အောက်ပါတွေကို သွင်းပေးပါမယ်:
   - Python package တွေ
   - Title စာရေးဖို့ လိုတဲ့ Chromium
   - **FFmpeg** — စက်ထဲမှာ မရှိရင် (~100 MB) download လုပ်ပြီး ဒီ folder ထဲက `ffmpeg\` ထဲ ထည့်ပေးပါမယ်။ PATH ထဲ (သို့) `C:\ffmpeg\bin\` မှာ ရှိပြီးသားဆိုရင် အဲ့ဒါကိုပဲ သုံးပါတယ်။
4. **`.env.example`** ကို **`.env`** လို့ copy ကူးပါ။ ပြီးရင် ဖွင့်ပြီး key ထည့်ပါ:
   ```ini
   GEMINI_API_KEY=ကိုယ့်_key
   ```
   Key တစ်ခုထက် ပိုရှိရင် (Google project တစ်ခုစီက key) ဒီလို ထည့်လို့ရပါတယ်။ တစ်ခုရဲ့ ကန့်သတ်ချက် ပြည့်ရင် နောက်တစ်ခုကို အလိုလို ပြောင်းသုံးပါတယ်။
   ```ini
   GEMINI_IMAGE_PROJECT_1_KEY=...
   GEMINI_IMAGE_PROJECT_2_KEY=...
   ```

> ⚠️ `.env` ထဲမှာ ကိုယ့် key ရှိလို့ ဘယ်သူ့ကိုမှ မပို့ပါနဲ့၊ GitHub ပေါ်လည်း မတင်ပါနဲ့ (`.gitignore` ထဲမှာ ထည့်ထားပြီးသားပါ)။

## သုံးနည်း

**`RUN.bat`** ကို double-click နှိပ်ပါ။ Window မှာ အကွက် ၃ ကွက် ပါပါတယ်။

| နေရာ | လုပ်ရမယ့်အရာ |
|---|---|
| အပေါ် | **Source Video → Browse** နဲ့ video ကို ရွေးပါ။ **Folder** နှိပ်ရင် folder ထဲက video တွေကို တစ်ခုပြီးတစ်ခု လုပ်ပါတယ် (ပြီးပြီးသား video တွေကို ကျော်ပါတယ်)။ **Gemini .env** မှာ `.env` ဖိုင်ကို ရွေးပါ (default က ဒီ folder ထဲက `.env`)။ **Save final to** — folder ရွေးထားရင် ပြီးတဲ့ video ကို `<video နာမည်>_Myanmar.mp4` နဲ့ အဲ့ folder ထဲ ထည့်ပေးပါတယ် (ဗလာထားရင် job folder ထဲမှာပဲ)။ |
| ဘယ်ဘက် | **Source language** (Auto-detect / English / Chinese / Hindi / Korean / …)၊ **Edge TTS Voice** (`my-MM-ThihaNeural` / `my-MM-NilarNeural`) နဲ့ **Edge TTS Speed** (−50% … +100%) ကို ရွေးပါ။ အောက်က **Run Logs** မှာ အလုပ်လုပ်နေတာတွေ ပြပါတယ်။ |
| အလယ် | **Preview** — slider နဲ့ `◀ 5s` / `5s ▶` နဲ့ ကြည့်ချင်တဲ့ အချိန်ကို ရွှေ့ပြီး **Refresh Frame** နှိပ်ပါ။ Title၊ Logo၊ Extra text ကို ဆွဲရွှေ့ပြီး နေရာချလို့ရပါတယ်။ Blur box ကို ဆွဲလို့ရပါတယ်။ |
| ညာဘက် | **Production Tools** — Zoom (1.00–1.25×)၊ Flip (ဘယ်ညာ ပြောင်းပြန်)၊ Voice vol (50–300%)၊ Short pauses၊ **Ratio** (16:9 / 9:16 / 1:1 / Original) နဲ့ **Fill** (Blur background / Black bars / Crop to fill)၊ **+ Draw Blur Box** / Delete Selected၊ Title (စာ၊ အရွယ်)၊ Logo (ဖိုင်၊ အရွယ်၊ အလင်းဖောက်မှု)၊ Extra Text Box။ |
| အောက်ခြေ | **START / RESUME** — စတယ် (ရပ်ထားတာဆိုရင် ဆက်လုပ်တယ်)။ **STOP SAFELY** — အခု လုပ်နေတဲ့ အဆင့်ပြီးမှ ရပ်ပြီး လုပ်ပြီးသမျှ သိမ်းထားတယ်။ **Open Job Folder** — ထွက်လာတဲ့ ဖိုင်တွေ ဖွင့်ကြည့်ဖို့။ **Edit Text** — မြန်မာ narration ကို စာကြောင်းလိုက် ပြင်ဖို့ (အောက်မှာ ကြည့်ပါ)။ |

**ထွက်လာတဲ့ ဖိုင်:** `jobs\<video နာမည်>_<code>\edge_tts_smart_sync\final_edge_tts_smart_sync.mp4`

Job folder ထဲမှာ ကြည့်လို့ရတဲ့ ဖိုင်တွေ:
- `whisper_transcript.txt` — မူရင်းဘာသာ စာသား
- `timestamp_translations.json` — စာပိုင်းတိုင်းရဲ့ မူရင်း နဲ့ မြန်မာ
- `smart_sync_plan.json` — အချိန်ညှိထားတဲ့ plan
- `run.log` — အလုပ်လုပ်သွားတဲ့ မှတ်တမ်း

## Splitter (ဗီဒီယို အပိုင်းခွဲ)

Window ထိပ်က **Splitter** tab ကို နှိပ်ပါ။ ရှည်တဲ့ video ကို မိနစ်အလိုက် အပိုင်းတွေ ခွဲပေးပါတယ် (TikTok / Reels / Facebook အတွက်)။

| | |
|---|---|
| **+ Videos / + Folder** | Video တစ်ခု (သို့) အများကြီး ထည့်ပါ။ အားလုံးကို setting တူတူနဲ့ တစ်ခုပြီးတစ်ခု ခွဲပါတယ်။ |
| **Save to** | ဗလာထားရင် video ဘေးက `<video နာမည်>_parts\` ထဲ သိမ်းပါတယ်။ Folder ရွေးထားရင် `<ရွေးထားတဲ့ folder>\<video နာမည်>_parts\` ထဲ။ ဖိုင်နာမည် `<video နာမည်>_part_01.mp4`, `_part_02.mp4` … |
| **Each part** | အပိုင်းတစ်ပိုင်း ဘယ်နှမိနစ်လဲ (0.5 … 60)။ နောက်ဆုံး အပိုင်းက အရမ်းတိုရင် (အပိုင်းအရှည်ရဲ့ ¼ နဲ့ 20 s အောက်) ရှေ့အပိုင်းထဲ ပေါင်းပါတယ်။ |
| **Smart cut** | ဖွင့်ထားရင် — အချိန်ပြည့်ချိန်မှာ စကားမဆုံးသေးရင် အများဆုံး **N စက္ကန့်** (default 20) အထိ စောင့်ပြီး စကားရပ်တဲ့နေရာ (စာကြောင်းဆုံး ဖြစ်နိုင်ခြေ အများဆုံး) မှာ ဖြတ်ပါတယ်။ ဥပမာ 3 မိနစ် ရွေးထားရင် 3:00 – 3:20 ကြားမှာ ဖြတ်ပါတယ်။ ပိတ်ထားရင် — 3:00 အတိ ဖြတ်ပါတယ်။ နောက်ခံ သီချင်း ရှိရင်လည်း စကားရပ်တာကို ရှာပါတယ်။ |
| **Check cuts** | ရွေးထားတဲ့ video ကို ဘယ်မှာ ဖြတ်မလဲ Parts ဇယားမှာ ကြိုကြည့်ဖို့။ |
| **Ratio / Fill** | **Original** = မူရင်းအတိုင်း။ **16:9 / 9:16 / 1:1** ဆိုရင် ကွက်လပ်ကို **Blur background** (နောက်ခံ ဝါးထားတဲ့ ပုံ) / Black bars / Crop to fill နဲ့ ဖြည့်ပါတယ်။ |
| **Text Box** | အပိုင်းတိုင်းမှာ ပေါ်မယ့် စာ (မြန်မာစာ ရပါတယ်)။ အရွယ်၊ Opacity၊ နောက်ခံ အမည်းကွက်။ Preview ပေါ်မှာ ဆွဲရွှေ့ပါ။ |
| **Part Number** | **Show** ကို ဖွင့်/ပိတ်ပါ။ `{n}` = 1, 2, 3 · `{mm}` = ၁, ၂, ၃ · `{total}` = အပိုင်း စုစုပေါင်း (`{mm}` သုံးရင် မြန်မာဂဏန်းနဲ့)။ ဥပမာ `Part {n}/{total}` → Part 2/5၊ `အပိုင်း {mm}/{total}` → အပိုင်း ၂/၅။ Preview ပေါ်မှာ ဆွဲရွှေ့ပါ။ |
| **START SPLIT / STOP** | STOP ပြီး ပြန် START ရင် ပြီးပြီးသား အပိုင်းတွေကို ချန်ပြီး ကျန်တာပဲ ဆက်လုပ်ပါတယ်။ Setting ပြောင်းရင် အပိုင်းတွေကို ပြန်လုပ်ပါတယ်။ |

အပိုင်းတိုင်းကို ပြန် encode လုပ်လို့ ဖြတ်တဲ့နေရာ အတိအကျ ဖြစ်ပါတယ် (NVIDIA GPU ရှိရင် NVENC နဲ့ မြန်ပါတယ် — 31 မိနစ် video ကို 9:16 + စာ + Part နံပါတ်နဲ့ 10 ပိုင်း ~4 မိနစ်)။

## Smart Sync ဘယ်လိုအလုပ်လုပ်လဲ

- **ရုပ်ကို အပိုင်းခွဲ** — စာပိုင်းတိုင်းက မူရင်း video ရဲ့ ရုပ်တစ်ပိုင်းကို ပိုင်တယ်။ စာပိုင်း ၂ ခုကြားက အသံတိတ်နေရာကို အလယ်ကနေ ခွဲပြီး ဘေးက စာပိုင်း ၂ ခုကို ဝေပေးတယ်။ Video ရဲ့ ပထမ frame ကနေ နောက်ဆုံး frame အထိ ဘာမှ မကျန်ပါဘူး (V2 full coverage)။
- **ရုပ်အပြည့် မဖြတ်ဘဲ ထိန်းထား** — စာပိုင်းတစ်ခုရဲ့ အသံက သူပိုင်တဲ့ မူရင်းရုပ်အပိုင်းထက် တိုရင် ရုပ်ကို မဖြတ်၊ မမြန်စေဘဲ မူရင်းအမြန်နှုန်းနဲ့ ဆက်ပြတယ်။ အသံတိုတဲ့နေရာမှာ အသံတိတ်ကို ဖြည့်ပြီး မူရင်း video အဆုံးအထိ ထိန်းထားတယ်။
- **အသံရှည်ရင် ရုပ်ကို နှေး** — narration က မူရင်းရုပ်အပိုင်းထက် ရှည်မှသာ အဲဒီရုပ်အပိုင်းကို နှေး (သို့) freeze frame ဖြန့်ပြီး အသံနဲ့ကိုက်စေတယ်။ ဒီအခါ output က မူရင်းထက် ပိုရှည်နိုင်တယ်၊ မူရင်းရုပ်ကိုတော့ ဖြတ်မပစ်ဘူး။
- **Frame ကို တွဲတွက်** — အပိုင်းတိုင်းရဲ့ frame အရေအတွက်ကို အသံရဲ့ စုစုပေါင်း အချိန်နဲ့ တွက်တယ် (30 fps)။ အပိုင်း ရာနဲ့ချီ ရှိနေတောင် ရုပ်နဲ့ အသံ frame တစ်ဝက်ထက် ပိုမကွာဘူး။ အဆုံးမှာ log က `SYNC OK: picture=… narration=… diff=…` လို့ ပြပါတယ်။
- **ပုံစံ (Ratio / Fill)** — NVIDIA ရှိရင် NVENC၊ မရှိရင် libx264 နဲ့ ထုတ်တယ်။

  | Ratio | Video အရွယ် |
  |---|---|
  | 16:9 (default) | 1920×1080 |
  | 9:16 (TikTok / Reels / Shorts) | 1080×1920 |
  | 1:1 | 1080×1080 |
  | Original | မူရင်း video ရဲ့ ပုံစံအတိုင်း (အရှည်ဘက် အများဆုံး 1920) |

  မူရင်းနဲ့ ပုံစံမတူရင် (ဥပမာ 16:9 video ကို 9:16 လုပ်ရင်) **Fill** နဲ့ ရွေးပါ:
  - **Blur background** — ပုံတစ်ခုလုံး မြင်ရပြီး ဘေးကွက်လပ်မှာ အဲ့ပုံကိုပဲ ဝါးပြီး ဖြည့်တယ်။
  - **Black bars** — ဘေးကွက်လပ်ကို အမည်းနဲ့ ဖြည့်တယ်။
  - **Crop to fill** — ပုံကို ချဲ့ပြီး frame ပြည့်အောင် လုပ်တယ်။ ဘေးက ပိုတဲ့အပိုင်းကို ဖြတ်တယ်။

  Zoom / Flip နဲ့ Title၊ Logo၊ Blur box တွေက ရွေးထားတဲ့ Ratio အတိုင်း ထွက်ပြီး preview မှာလည်း ဒီအတိုင်း ပြတယ်။

## Gemini key နဲ့ ကန့်သတ်ချက်

- Gemini ကို **ဘာသာပြန်ဖို့ပဲ** သုံးတယ်။ English ကို စာသားပြောင်းတာက စက်ထဲမှာ Whisper နဲ့ လုပ်တယ်။
- အခမဲ့ key မှာ တစ်ရက်ကို သုံးလို့ရတဲ့ အကြိမ်ရေ ကန့်သတ်ထားတယ် (Google project တစ်ခုချင်းစီ အလိုက်)။ ပြည့်ရင်:
  - နောက် key ကို အလိုလို ပြောင်းတယ်။
  - Key တွေ အကုန်ပြည့်ရင် နောက် model ကို ပြောင်းတယ် (`gemini-3.5-flash → 3.5-flash-lite → 3.6-flash → 3.7-flash → 3.1-flash-lite`)။
  - အကုန်ပြည့်သွားရင် ရပ်သွားပေမဲ့ ပြီးသမျှ မပျောက်ဘူး။ နောက်နေ့ (သို့) key အသစ်ထည့်ပြီး **START / RESUME** နှိပ်ရင် ရပ်ခဲ့တဲ့နေရာကနေ ဆက်တယ်။
- Gemini ကို VPN / proxy နဲ့မှ သုံးလို့ရတဲ့ စက်ဆိုရင် `.env` ထဲမှာ `GEMINI_PROXY=http://127.0.0.1:10808` (ကိုယ့် proxy လိပ်စာ) ထည့်ပါ။ `127.0.0.1:10808` (v2rayN) ဖွင့်ထားရင် အလိုလို သုံးပါတယ်။ အမြဲ တိုက်ရိုက်ပဲ သုံးချင်ရင် `GEMINI_PROXY=none` ထည့်ပါ။ Edge TTS ကတော့ proxy မသုံးဘဲ တိုက်ရိုက် အရင်စမ်းပါတယ်။

## အဆင့်မြင့် ပြင်ဆင်ချက် (`config.json`)

Tool ဖွင့်ပြီး START နှိပ်လိုက်ရင် `config.json` ကို အလိုလို ဖန်တီးပေးပါတယ် (UI မှာ ရွေးထားတာတွေ သိမ်းဖို့ပါ)။ လိုမှပဲ ပြင်ပါ:

| Key | Default | အဓိပ္ပာယ် |
|---|---|---|
| `ffmpeg_path`, `ffprobe_path` | (အလိုလို ရှာ) | FFmpeg ဖိုင် လမ်းကြောင်း |
| `python_path` | (အလိုလို ရှာ) | `RUN.bat` သုံးမယ့် Python |
| `max_video_speed` | `1.25` | ရုပ်ကို မြန်စေနိုင်တဲ့ အများဆုံး ဆ |
| `translation_batch_max_items` | `40` | Gemini တစ်ခါမေးရင် ပါမယ့် စာပိုင်းအရေအတွက် |
| `atomic_target_duration`, `atomic_max_duration` | `4.2`, `5.6` | စာပိုင်းတစ်ပိုင်းရဲ့ အရှည် (စက္ကန့်) |
| `translation_audit` | `true` | ပြန်ပြီးတိုင်း စစ်ဆေးတဲ့ အဆင့် |
| `title_font_path` | `C:\Windows\Fonts\mmrtext.ttf` | Title / Extra text ဖောင့် |
| `overlay_blur_strength` | `18` | Blur box ရဲ့ ဝါးအား |
| `whisper_model_other` | `medium` | English မဟုတ်တဲ့ ဘာသာအတွက် Whisper model (NVIDIA GPU မရှိတဲ့ စက်မှာ `small` က ပိုမြန်တယ်) |

## စာကြောင်း ခွဲပုံ

English စာကို **စာကြောင်း (sentence) တစ်ကြောင်းချင်း** ခွဲပြီး ဘာသာပြန်ပါတယ် (VoxCPM recap လိုပါပဲ)။ စာကြောင်း တစ်ဝက်ကနေ မဖြတ်တော့လို့ Gemini က စာကြောင်းတစ်ကြောင်းကို နှစ်ခါ မပြောတော့ပါဘူး။ စာကြောင်းရှည်ရင် ကော်မာ (သို့) အသက်ရှူတဲ့ နေရာမှာ ဖြတ်ပါတယ် (အများဆုံး ၂၄ စက္ကန့်)။ Version အဟောင်းနဲ့ ဘာသာပြန်ပြီးသား job ကို resume လုပ်ရင်တော့ ဖြတ်ပုံဟောင်း (၄–၆ စက္ကန့်) နဲ့ပဲ ဆက်လုပ်ပါတယ် — ဘာသာပြန်ပြီးသားနဲ့ အသံတွေ မပျက်အောင်ပါ။

## စာသား ပြင်နည်း (Edit Text)

ဘာသာပြန်ပြီးသွားရင် **Edit Text** နှိပ်ပြီး စာကြောင်းတိုင်းရဲ့ English မူရင်းနဲ့ မြန်မာ narration ကို ဘေးချင်းယှဉ် ကြည့်ပြီး ပြင်လို့ရပါတယ်။
- **Prev / Next / Go** — စာကြောင်း ရွှေ့ကြည့်ပါ။ **Next problem** — English စာလုံး၊ တခြားဘာသာ စာလုံး ရောနေတဲ့ စာကြောင်းကို ရှာပေးပါတယ်။
- ပြင်ပြီး **Save** နှိပ်ပါ → **START / RESUME** နှိပ်ရင် ပြင်ထားတဲ့ စာကြောင်းကိုပဲ အသံ အသစ်ထုတ်ပြီး ကျန်တာ ပြန်သုံးပါတယ်။
- Render လုပ်နေရင်း စာကြောင်းတစ်ကြောင်း အသံထွက်မလာလို့ ရပ်သွားရင် (ဥပမာ English နဲ့ မြန်မာ ရောနေလို့) ဘယ်စာကြောင်းမှာ ရပ်လဲ ပြပြီး Edit Text ကို အဲ့စာကြောင်းမှာ ဖွင့်ပေးပါတယ်။

## ပြဿနာ ဖြေရှင်းနည်း

| တွေ့ရတာ | လုပ်ရမယ့်အရာ |
|---|---|
| `Python with the required packages was not found` | `INSTALL_REQUIREMENTS.bat` ကို ပြန် run ပါ။ Python 3.12 ကို PATH ထဲ ထည့်ထားဖို့ လိုပါတယ်။ |
| `Gemini API key မတွေ့ပါ` | `.env` ရှိမရှိ၊ `GEMINI_API_KEY=` နောက်မှာ key ပါမပါ စစ်ပါ။ UI ရဲ့ **Gemini .env** မှာ မှန်ကန်တဲ့ ဖိုင်ကို ရွေးပါ။ |
| `key pool exhausted` / 429 | ဒီနေ့ ကန့်သတ်ချက် ပြည့်သွားလို့ပါ။ Key ထပ်ထည့်ပါ (သို့) နောက်နေ့ **START / RESUME** နှိပ်ပါ။ |
| `open() got an unexpected keyword argument 'metadata_errors'` | `av` version အသစ် (19) ကြောင့်ပါ။ Repo အသစ်ကို ပြန် download လုပ်ပြီး `INSTALL_REQUIREMENTS.bat` ကို ပြန် run ပါ (`av==18.0.0` ကို သွင်းပေးပါမယ်)။ |
| Log မှာ `GPU Whisper failed … using the CPU instead` | NVIDIA GPU ရှိပေမဲ့ CUDA 12 library (cuBLAS/cuDNN) မရှိလို့ CPU နဲ့ ဆက်လုပ်တာပါ။ အလုပ်ပြီးပါတယ်၊ နည်းနည်းပဲ ပိုကြာပါတယ်။ |
| `You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN…` ပြပြီး ရပ်နေသလို ဖြစ်နေတယ် | HF token **မလိုပါဘူး**။ Warning သက်သက်ပါ။ ပထမဆုံးအကြိမ်မှာ Whisper model (English ~460 MB၊ တခြားဘာသာ ~1.5 GB) ကို download လုပ်နေတာပါ။ Log မှာ `⬇️ Whisper model: … MB downloaded` လို့ ၅ စက္ကန့်တစ်ခါ ပြပါတယ်။ တစ်ခါပဲ download လုပ်ရပါတယ်။ huggingface.co မဖွင့်ရတဲ့ စက်ဆိုရင် VPN သုံးပါ (သို့) `.env` ထဲမှာ `HF_ENDPOINT=https://hf-mirror.com` ထည့်ပါ။ |
| Edge TTS `NoAudioReceived` | Internet ကို စစ်ပါ။ Tool က တိုက်ရိုက် ၂ ကြိမ်၊ system proxy နဲ့ ၂ ကြိမ် ပြန်စမ်းပါတယ်။ English စာလုံး ရောနေတဲ့ စာကြောင်းဆိုရင် English စာလုံးတွေ ချန်ပြီး တစ်ခါ ထပ်စမ်းပါတယ်။ |
| `403, message='Invalid response status'` (`WSServerHandshakeError`) | Microsoft ရဲ့ အသံ service က ချိတ်ဆက်မှုကို ငြင်းတာပါ — VPN / proxy server တော်တော်များများကို ငြင်းပါတယ်။ **VPN ဖွင့်ထားရင် ပိတ်ပါ** (သို့) server ပြောင်းပါ။ ကွန်ပျူတာ နာရီ/Time zone ကို Settings → Time & language → Set time automatically နဲ့ မှန်အောင်ထားပါ။ မရသေးရင် `INSTALL_REQUIREMENTS.bat` ကို ပြန် run ပါ (edge-tts ကို update လုပ်ပါတယ်)။ ပြီးရင် **START / RESUME**။ VPN မပါရင် မရတဲ့ network ဆိုရင် `.env` ထဲမှာ `EDGE_TTS_PROXY=http://127.0.0.1:<port>` ထည့်ပါ။ |
| `Whisper က … စကားကို ကောင်းကောင်း မကြားရပါဘူး` (သို့) `whisper_transcript.txt` ထဲမှာ "I'm not going to do it." လို စာကြောင်း တူတူတွေ ထပ်ခါထပ်ခါ ရေးထားတယ် | Whisper က ဘာသာ မှားပြီး နားထောင်နေတာပါ (ဥပမာ ဟိန္ဒီ video ကို English လို)။ **Source language** မှာ မှန်တဲ့ ဘာသာကို ရွေးပြီး (သို့) Auto-detect နဲ့ **START / RESUME** ပြန်နှိပ်ပါ။ ဘာသာ မှန်ပါလျက် ဒီ error တက်ရင် `whisper_transcript.txt` ကို စစ်ပါ (သီချင်း / ဆူညံသံ များတာ ဖြစ်နိုင်ပါတယ်)။ ဘာသာပြန်မစခင် ရပ်တာမို့ Gemini quota မကုန်ပါဘူး။ |
| `The video already speaks Burmese` | Auto-detect က မြန်မာစကားလို့ ကြားတာပါ။ မှားရင် Source language မှာ ရွေးပါ။ |
| Gemini `User location is not supported for the API use` | Gemini က ကိုယ့် internet (VPN server) ရဲ့ နိုင်ငံကို လက်မခံတာပါ။ VPN server (နိုင်ငံ) ပြောင်းပြီး **START / RESUME** ပြန်နှိပ်ပါ။ |
| `Edge TTS FAILED at segment 123` | အဲ့စာကြောင်းမှာ အသံ မထွက်လို့ ရပ်တာပါ။ **Yes** နှိပ်ရင် Edit Text ပွင့်လာပါမယ် — မြန်မာလို ပြင်ပြီး Save → **START / RESUME**။ |
| `Gemini JSON response failed after 3 attempts` | Gemini ရဲ့ အဖြေ ပျက်နေတာပါ။ **START / RESUME** ပြန်နှိပ်ရင် ဆက်လုပ်ပါတယ်။ (Story context အဆင့်မှာဆိုရင် အခု version က အဲ့အပိုင်းကို ချန်ပြီး ဆက်သွားလို့ မရပ်တော့ပါ။) |
| `[WinError 2] The system cannot find the file specified` (သို့) `ffmpeg.exe မတွေ့ပါ` (Preview မှာ `00:00 / 00:00`) | FFmpeg မရှိလို့ပါ။ `INSTALL_REQUIREMENTS.bat` ကို ပြန် run ပါ (FFmpeg ကို `ffmpeg\` ထဲ ထည့်ပေးပါမယ်)။ (သို့) gyan.dev ကနေ download လုပ်ပြီး `ffmpeg.exe`၊ `ffprobe.exe` ကို `RUN.bat` ဘေးက `ffmpeg` folder ထဲ ထည့်ပါ။ |
| Title မြန်မာစာ မပေါ်ဘူး | `py -3.12 -m playwright install chromium` ကို run ပါ။ ဖောင့်ကို `RECAP_MM_FONT` (environment variable) (သို့) `title_font_path` နဲ့ ပြောင်းလို့ရပါတယ်။ |
| Log မှာ `⚠️ ID 00012: removed letters of another script` | Gemini က မြန်မာစာထဲ တခြားဘာသာ စာလုံး ထည့်ခဲ့လို့ ဖယ်ထားတာပါ။ အဲ့စာကြောင်းကို `timestamp_translations.json` ထဲမှာ ကြည့်ပါ။ |

## Folder ဖွဲ့စည်းပုံ

```
RUN.bat                    UI ဖွင့်ဖို့
INSTALL_REQUIREMENTS.bat   Python package + Chromium သွင်းဖို့
.env.example               Gemini key ပုံစံ (.env လို့ copy ကူးပါ)
requirements.txt
app/
  controller.py            UI (tkinter): preview၊ overlay၊ job တွေ စီမံတာ
  planner_worker.py        အဆင့် ၁: Whisper → story context → ဘာသာပြန် → Smart Sync plan
  recap_planner.py         Planner (စာပိုင်းခွဲ၊ Gemini prompt၊ audit၊ ID စစ်တာ)
  render_worker.py         အဆင့် ၂: Edge TTS → Smart Sync render
  core.py                  Edge TTS, Short pauses, Smart Sync, overlay, mux
  preview_tools.py         Preview frame / logo
  splitter.py              Splitter: ဘယ်မှာ ဖြတ်မလဲ (smart cut)၊ အပိုင်း render
  splitter_tab.py          Splitter tab UI
  launch.ps1               Python ရှာပြီး UI ဖွင့်တာ
recap_runtime/services/
  whisper_service.py       faster-whisper (GPU / CPU)
  ai_service.py            Gemini client (proxy option)
services/
  text_overlay_service.py  မြန်မာ title စာကို Chromium နဲ့ ပုံထုတ်တာ
tests/                     python -m unittest discover -s tests
```

## Test

```bat
py -3.12 -m unittest discover -s tests
```
Internet မလိုပါဘူး။ Gemini ကို အတုနဲ့ အစားထိုး စမ်းပါတယ်။

## သတိပြုရန်

- Edge TTS က Microsoft ရဲ့ online ဝန်ဆောင်မှုပါ။ Gemini ကတော့ Google ရဲ့ API ပါ။ သူတို့ရဲ့ စည်းကမ်းချက်တွေကို လိုက်နာပါ။
- သုံးမယ့် video ရဲ့ မူပိုင်ခွင့်ကို ကိုယ်တိုင် တာဝန်ယူပါ။

---

## English

**Recap → Myanmar** turns a recap/story video narrated in any language Whisper knows (English, Chinese,
Hindi, Korean, Japanese, Thai, …) into a Myanmar-narrated one on Windows. The **Splitter** tab cuts long
videos into parts.

### How it works
1. **Listen** — local Whisper (faster-whisper; NVIDIA GPU or CPU) writes the speech with word timestamps.
   **Source language** = Auto-detect lets the multilingual `base` model listen to the first 8 minutes
   first; English is heard by `small.en` (~460 MB), any other language by the multilingual `medium`
   (~1.5 GB; `"whisper_model_other": "small"` in config.json is faster on a PC without an NVIDIA GPU).
   Hindi and Urdu sound alike, so an Auto-detected "Urdu" is written as Hindi (choose Urdu to keep Urdu
   letters). Where Whisper writes few sentence marks, the end of a Whisper segment counts as a sentence end.
2. **Split** — sentence/clause/pause boundaries give short sync units (about 4.2 s, at most 5.6 s);
   more units = more sync anchors.
3. **Story memory** — Gemini reads the whole transcript first and keeps names, relationships and
   places consistent.
4. **Translate** — Gemini translates 40 units per request into natural spoken Burmese narration
   (no summary, no shortening, every unit keeps its own content), then an audit pass repairs
   omissions/shifts/duplicates. Letters of another script inside the Burmese (e.g. Georgian "მის"
   inside "ဧည့်ခန်း") are asked again, and if still there removed and logged.
5. **Voice** — Microsoft Edge TTS Myanmar voices (Thiha / Nilar). "Short pauses" trims the silence
   Edge puts around each clip (~0.25 s between lines instead of ~1 s).
6. **Smart Sync** — every unit owns a window of the original picture (the silence between two units
   is split at its middle, so the whole video is used). If its Myanmar voice is shorter than that
   window, silence fills the remainder; if longer, the voice is sped up to fit. Every original
   picture interval is retained and the output stays the same duration as the source. Frame counts
   are cumulative at 30 fps; `SYNC OK … diff=…` compares picture and narration duration.
   Output ratio **16:9** (1920×1080), **9:16** (1080×1920), **1:1** (1080×1080) or **Original**
   (the source shape, long side at most 1920); when the source has another shape, **Fill** decides:
   Blur background, Black bars or Crop to fill. Optional zoom/flip; NVENC or libx264.
7. **Subtitles** — optional original-transcript captions, timed to the Myanmar voice and off by default. Enable “Show original transcript captions” in the Video settings to burn them in. Use a Blur Box to hide subtitles already embedded in the source video.
8. **Production tools** — blur boxes, title, logo and an extra text box placed on the preview.

The output has only the Myanmar voice (no original audio or music).

### Requirements
Windows 10/11 64-bit · Python 3.12 64-bit (with tcl/tk, on PATH) · FFmpeg (`ffmpeg.exe` +
`ffprobe.exe` on PATH, in `C:\ffmpeg\bin`, or in a folder named `ffmpeg` here) · a free Gemini API
key ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)) · internet. An NVIDIA GPU is
optional (without the CUDA 12 libraries Whisper falls back to the CPU by itself).

### Install
1. Download the repo (Code → Download ZIP) and unzip it.
2. Run **`INSTALL_REQUIREMENTS.bat`** (pip packages, Chromium for the Myanmar title renderer, and
   FFmpeg: when it is not on PATH or in `C:\ffmpeg\bin`, about 100 MB is downloaded into `ffmpeg\`).
   `[WinError 2] The system cannot find the file specified` means FFmpeg is missing — run it again.
3. Copy **`.env.example`** to **`.env`** and set `GEMINI_API_KEY=`. More keys
   (`GEMINI_IMAGE_PROJECT_1_KEY`, `GEMINI_IMAGE_PROJECT_2_KEY`, …) are used in turn when one is used
   up; after all keys the next model is tried
   (`gemini-3.5-flash → 3.5-flash-lite → 3.6-flash → 3.7-flash → 3.1-flash-lite`).
   If Gemini needs a proxy, add `GEMINI_PROXY=http://host:port` (a running v2rayN on
   `127.0.0.1:10808` is used automatically; `GEMINI_PROXY=none` forces direct).

Never share or commit your `.env` (it is in `.gitignore`).

The first run downloads the Whisper model (~460 MB for English, ~1.5 GB for other languages) from
huggingface.co; the log shows
`⬇️ Whisper model: … MB downloaded`. No account or HF_TOKEN is needed — the "unauthenticated
requests" line is only a warning. If huggingface.co does not open, use a VPN or set
`HF_ENDPOINT=https://hf-mirror.com` in `.env`.

### Use
Double-click **`RUN.bat`**:
- **Source Video** → Browse, or drop a video on the empty preview (use **Folder...** for a batch; finished videos are skipped).
- **Save final to** — when a folder is chosen, each finished video is also saved there as
  `<video name>_Myanmar.mp4`.
- **Source language** (Auto-detect, English, Chinese, Hindi, …), **Edge TTS Voice / Speed** on the left.
- **Preview** in the middle: seek, Refresh Frame, drag the title/logo/text, draw blur boxes.
- **Editing Inspector** on the right: use the accordion sections for Playback, Blur Watermark Area,
  Title, Logo and Extra Text Box.
- **START / RESUME** — starts or continues; **STOP SAFELY** — stops at a safe point and keeps
  everything; **Open Job Folder**; **Edit Text** — read each English line next to its Burmese narration,
  fix the Burmese and Save; START / RESUME then re-voices only the edited lines. When a line gets no
  audio (e.g. English and Burmese mixed), the error names the line and offers to open Edit Text on it.
- Lines are whole English sentences (like the VoxCPM recap tool), so a sentence is never cut in two and told
  twice; a long sentence ends at a comma or a breath (24 s at most). A job translated with an older version
  keeps its 4-6 s lines when resumed.
- When Whisper listens for the wrong language it writes a few phrases again and again ("I'm not going to do
  it." ×40); when a quarter of the Whisper lines repeat, the job stops before translating (no Gemini quota
  used) — choose the right Source language (or Auto-detect) and start again.
- On long videos, an unusually short transcript is retried without VAD. If the two passes corroborate a short
  low-dialogue transcript, it is kept; if they disagree or the retry cannot confirm it, the job stops for
  transcript review instead of producing a potentially incomplete recap. The render also blocks a sub-6-second
  narration from an unverified long-source transcript. Check `whisper_transcript.txt`, the source audio, and
  Source language before retrying.
- Gemini `User location is not supported for the API use`: Gemini refuses the country of your internet /
  VPN server — change the VPN server and START / RESUME.

### Splitter tab
- **+ Videos / + Folder**, **Save to** (empty = `<video folder>\<name>_parts\`; files `<name>_part_01.mp4` …).
- **Each part** N minutes. **Smart cut** on: when the time is up in the middle of speech, it waits up to
  20 s (adjustable) and cuts in the pause most likely to end a sentence (also under background music); off:
  exact cuts. A last piece shorter than a quarter part (and 20 s) joins the part before it.
  **Check cuts** lists where the selected video will be cut.
- **Ratio** Original / 16:9 / 9:16 / 1:1 with **Fill** Blur background / Black bars / Crop to fill.
- **Text Box** and **Part Number** (`{n}` 1 2 3, `{mm}` ၁ ၂ ၃, `{total}` — in Myanmar digits too when `{mm}` is
  used), size / opacity / dark box, dragged on the preview.
- **START SPLIT / STOP**: a stopped split goes on from the first unfinished part; changed settings remake
  the parts. Every part is re-encoded so cuts are exact (NVENC when available).
- Edge TTS `403 Invalid response status`: Microsoft refuses many VPN / proxy servers — turn the VPN off (or
  change server), set the Windows clock automatically, or run INSTALL_REQUIREMENTS.bat again; on a network that
  needs a proxy put `EDGE_TTS_PROXY=http://127.0.0.1:<port>` in the .env.

Result: `jobs\<name>_<code>\edge_tts_smart_sync\final_edge_tts_smart_sync.mp4`
(plus `whisper_transcript.txt`, `timestamp_translations.json`, `smart_sync_plan.json`, `run.log`).

### Advanced (`config.json`, created on the first START)
`ffmpeg_path`, `ffprobe_path`, `python_path`, `max_video_speed` (1.25),
`translation_batch_max_items` (40), `atomic_target_duration` / `atomic_max_duration` (4.2 / 5.6),
`translation_audit` (true), `title_font_path`, `overlay_blur_strength` (18),
`whisper_model_other` ("medium"; the Whisper model for languages other than English).

### Tests
`py -3.12 -m unittest discover -s tests` (offline; Gemini is mocked).

### Notes
Edge TTS is a Microsoft online service and Gemini is a Google API — follow their terms. You are
responsible for the rights to the videos you process.
