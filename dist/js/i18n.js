(() => {
  'use strict';
  const translations = Object.fromEntries([
    ['My Prosthetic','我的義肢'],['My Order','我的訂單'],['My Delivery','配送進度'],['My Account','我的帳戶'],
    ['Sign in','登入'],['Create your cover','設計保護套'],['Create a cover','設計保護套'],['How it works','了解流程'],
    ['Custom prosthetic covers · Hong Kong','訂製義肢保護套 · 香港'],
    ['PERSONAL DESIGN, REIMAGINED','重新想像個人設計'],['A cover that feels','一款真正屬於'],['like yours.','你的保護套。'],
    ['Turn a short video of your prosthesis into a cover shaped for you. Choose a finish, select a material, and we’ll make it here for your next chapter.','上傳義肢短片，選擇樣式、顏色與材料，讓我們為你設計專屬保護套。'],
    ['Made for Hong Kong, made for you.','為香港製作，為你而設。'],['FORM, FUNCTION, FREEDOM','造型、功能、自由'],
    ['Shape your story','塑造你的風格'],['Designed around your prosthesis','依照你的義肢設計'],
    ['01 Built around you','01   為你量身設計'],['02 Finished your way','02   自選外觀'],['03 Delivered in Hong Kong','03   香港配送'],
    ['THE PROCESS','設計流程'],['From a video to','從一段影片開始，'],['your own design.','打造專屬設計。'],
    ['A clear path from your video and chosen style to design review.','從上傳影片、選擇樣式，到設計審核，每一步都清晰可見。'],
    ['Record','拍攝'],['Capture your prosthesis from every side.','從各個方向拍攝義肢。'],
    ['Parameters','選擇樣式'],['Choose a style and color for your cover.','選擇保護套樣式和顏色。'],
    ['Modeling','建模'],['Follow the progress of your custom model.','查看專屬模型的處理進度。'],
    ['Coloring','設計審核'],['Our team reviews the design and material options.','由團隊審核設計和材料選項。'],
    ['Payment','下單'],['Ordering opens after design approval.','設計獲批後開放下單。'],
    ['Shipping','寄送'],['Shipping details will be shared when available.','寄送安排確定後會通知你。'],
    ['Delivery','收件'],['Your finished cover is delivered after production.','製作完成後寄送保護套。'],
    ['READY WHEN YOU ARE','準備好就開始'],['Make it','打造'],['your own.','專屬設計。'],
    ['Sign in to upload your video, choose a style, and follow design progress.','登入後上傳影片、選擇樣式，並追蹤設計進度。'],
    ['Sign in to Forme','登入 Forme'],['MADE FOR YOUR FORM','為你的形態而設'],['Design begins','設計從'],['with you.','你開始。'],
    ['Your ideas, your finish, your next chapter.','你的想法、你的風格、你的新篇章。'],['← Back to home','← 返回首頁'],
    ['WELCOME BACK','歡迎回來'],['Sign in to upload a video and follow your design.','登入後上傳影片並追蹤設計進度。'],
    ['Access key','登入密鑰'],['Your access key is provided by Forme. Keep it private.','請使用 Forme 提供的密鑰，並妥善保管。'],
    ['YOUR DESIGN STUDIO','你的設計工作室'],['Create your cover','設計保護套'],
    ['Start with your prosthesis, then shape the details that make it yours.','先拍攝義肢，再選擇屬於你的設計細節。'],
    ['1. Record','1. 拍攝'],['2. Model','2. 模型'],['3. Color','3. 樣式與顏色'],['4. Material','4. 材料'],
    ['01 / RECORD','01 / 拍攝'],['Show us your prosthesis.','讓我們看看你的義肢。'],
    ['Record a slow, steady video around your prosthesis in good light. Include a 200 mm scale target. Capture front, back, both sides, then tilt above for a clear top-opening view and show the bolt side up close.','在充足光線下緩慢環繞拍攝義肢，並放入 200 mm 標定尺。請拍攝正面、背面、左右兩側、清晰的上口俯視和螺栓近照。'],
    ['Choose a video to upload','選擇影片上傳'],['MP4, MOV, or WebM · up to 512 MB','MP4、MOV 或 WebM · 最大 512 MB'],
    ['Recording tip','拍攝提示'],['Move slowly around the prosthesis and keep it centered in the frame.','緩慢環繞義肢拍攝，並讓義肢保持在畫面中央。'],
    ['02 / MODEL','02 / 模型'],['Your base model.','你的基礎模型。'],
    ['Your video is uploaded for quality review. Our team checks your video before creating the reference model. Your style and color choices are saved with the submission.','影片上傳後會先進行品質檢查，再建立參考模型。你選擇的樣式和顏色會隨提交資料儲存。'],
    ['Waiting for video upload','等待影片上傳'],['The preview is illustrative, not your generated model.','預覽為樣式示意，並非你的專屬模型。'],
    ['Next, make it yours','接下來選擇你的風格'],['Add a color finish and choose a printing material.','選擇顏色和打印材料。'],
    ['03 / COLOR','03 / 樣式與顏色'],['Find your finish.','選擇你的外觀。'],
    ['Choose a palette or share an image and a few words to inspire a custom finish.','選擇顏色，或上傳圖片並描述想要的風格。'],
    ['COVER STYLES','保護套樣式'],['Rotate the 3D preview to explore the selected style. The final cover will be adapted to your prosthesis.','旋轉 3D 預覽查看樣式。最終保護套會依照你的義肢調整。'],
    ['COLOR FINISH','顏色'],['Satin Silver','緞面銀'],['Deep Charcoal','深炭灰'],['Soft Sand','柔沙色'],['Ocean Blue','海洋藍'],
    ['Custom color','自訂顏色'],['YOUR INSPIRATION','你的靈感'],['OPTIONAL','選填'],['Describe the finish you imagine','描述你想要的外觀'],
    ['＋ Add an inspiration image','＋ 上傳靈感圖片'],['04 / MATERIAL','04 / 材料'],['Choose your material.','選擇材料。'],
    ['Each option has a distinct feel. Final material availability and pricing will be confirmed after design review.','每種材料各有不同質感；最終供應情況和價格會在設計審核後確認。'],
    ['Lightweight Polymer','輕量聚合物'],['Comfortable for everyday wear · smooth finish','適合日常使用 · 表面平滑'],
    ['Durable Nylon','耐用尼龍'],['Flexible strength · fine surface texture','有彈性且堅韌 · 細緻紋理'],
    ['Premium Resin','精細樹脂'],['High detail · refined appearance','細節豐富 · 外觀精緻'],
    ['← Back','← 返回'],['Continue','繼續'],['LIVE DESIGN PREVIEW','即時設計預覽'],['STYLE','樣式'],['FINISH','顏色'],['MATERIAL','材料'],
    ['Auspicious Cloud','祥云'],['Style preview only. Your personal cover model is created after video review.','這是樣式預覽；影片審核後才會建立你的專屬模型。'],
    ['YOUR COLLECTION','你的設計'],['Review your submitted designs and follow video and modeling progress.','查看已提交的設計，以及影片和建模進度。'],
    ['YOUR SPACE','你的帳戶'],['Your Forme profile and design activity.','查看你的 Forme 資料和設計紀錄。'],
    ['ORDER HISTORY','訂單紀錄'],['See every cover you\'ve ordered and its current status.','查看保護套訂單與目前狀態。'],
    ['YOUR SHIPMENTS','配送紀錄'],['Follow your cover from production through arrival.','追蹤保護套的製作及配送。'],
    ['ORDERING','下單'],['Ordering opens after review','審核後開放下單'],['We will share ordering details when your design has been reviewed.','設計完成審核後，我們會提供下單詳情。'],
    ['Enter your access key','輸入登入密鑰'],['A calm blue with a subtle matte finish...','帶有柔和啞光質感的海藍色…']
  ]);
  const locale = localStorage.getItem('forme_locale') === 'zh-Hant' ? 'zh-Hant' : 'en';
  window.FormeI18n = { locale, t: (en, zh) => locale === 'zh-Hant' ? zh : en };
  function translate() {
    document.documentElement.lang = locale === 'zh-Hant' ? 'zh-Hant' : 'en';
    if (locale === 'zh-Hant') {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      for (const node of nodes) {
        if (node.parentElement?.closest('script,style')) continue;
        const trimmed = node.nodeValue.trim();
        const normalized = trimmed.replace(/\s+/g, ' ');
        if (translations[normalized]) node.nodeValue = node.nodeValue.replace(trimmed, translations[normalized]);
      }
      for (const element of document.querySelectorAll('[placeholder],[aria-label],[alt]')) {
        for (const attribute of ['placeholder', 'aria-label', 'alt']) {
          const value = element.getAttribute(attribute);
          if (value && translations[value]) element.setAttribute(attribute, translations[value]);
        }
      }
      if (translations[document.title]) document.title = translations[document.title];
    }
    const target = document.querySelector('.site-header') || document.querySelector('.auth-panel');
    if (target) {
      const switcher = document.createElement('button');
      switcher.type = 'button';
      switcher.className = 'language-switch';
      switcher.textContent = locale === 'zh-Hant' ? 'English' : '繁體中文';
      switcher.setAttribute('aria-label', locale === 'zh-Hant' ? 'Switch to English' : '切換至繁體中文');
      switcher.addEventListener('click', () => {
        localStorage.setItem('forme_locale', locale === 'zh-Hant' ? 'en' : 'zh-Hant');
        location.reload();
      });
      target.append(switcher);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', translate, { once: true });
  else translate();
})();
