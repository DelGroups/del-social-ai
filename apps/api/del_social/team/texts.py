"""What the team says by itself (events, chat notes, step results), in the owner's language (ADR 010).

The owner talks to the team in any language; the team answers in the language of the owner's
latest message (detected by code from the script and letters), unless the brand profile fixes a
report language. Content for the social pages is not affected: the Copywriter always writes the
brand's languages (Azerbaijani + Russian).
"""
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

LANGS = ("az", "ru", "en", "fa")
DEFAULT = "az"

_AZ_LETTERS = re.compile(r"[əğışçöüƏĞİŞÇÖÜ]")
_AZ_WORDS = re.compile(
    r"\b(salam|necesen|və|ve|üçün|ucun|nə|bu|bir|mən|men|sən|biz|necə|nece|hazırla|hazirla|var|yox|olsun|edin|et|bazar|rəqib|sabah|axşam)\b", re.I
)
_EN_WORDS = re.compile(r"\b(the|and|please|what|how|make|for|with|today|tomorrow|market|competitors?|is|are|you|we|our|prepare|show)\b", re.I)


def detect(text: str) -> str | None:
    """Language of a message by its script: Persian (Arabic script), Russian (Cyrillic), Azerbaijani, English."""
    t = text or ""
    arabic = len(re.findall(r"[؀-ۿ]", t))
    cyrillic = len(re.findall(r"[Ѐ-ӿ]", t))
    latin = len(re.findall(r"[A-Za-zƏəĞğİıŞşÇçÖöÜü]", t))
    if max(arabic, cyrillic, latin) == 0:
        return None
    if arabic >= max(cyrillic, latin):
        return "fa"
    if cyrillic >= latin:
        return "ru"
    # Latin script: Azerbaijani letters count double; otherwise whichever language's common words win
    az = 2 * len(_AZ_LETTERS.findall(t)) + len(_AZ_WORDS.findall(t))
    en = len(_EN_WORDS.findall(t))
    return "en" if en > az else "az"


async def language_of(db: AsyncSession) -> str:
    """The team's language for this company now (tenant context must be set)."""
    from del_social.models import BrandProfileVersion, ChatMessage  # models import this package's siblings

    brand = await db.scalar(select(BrandProfileVersion).order_by(BrandProfileVersion.version.desc()).limit(1))
    fixed = (((brand.data or {}).get("market") or {}).get("report_language") if brand else None) or "auto"
    if fixed in LANGS:
        return fixed
    for m in (await db.scalars(
        select(ChatMessage).where(ChatMessage.role == "user").order_by(ChatMessage.created_at.desc()).limit(5)
    )).all():
        if lang := detect(m.text):
            return lang
    return DEFAULT


@dataclass(frozen=True)
class Msg:
    """A message written in the owner's language when it is stored."""

    key: str
    params: dict[str, Any] = field(default_factory=dict)

    def render(self, lang: str) -> str:
        texts = CATALOG[self.key]
        template = texts.get(lang) or texts[DEFAULT]
        values = {k: (v.render(lang) if isinstance(v, Msg) else v) for k, v in self.params.items()}
        return template.format(**values)


def m(key: str, **params: Any) -> Msg:
    assert key in CATALOG, key
    return Msg(key, params)


def text_of(value: "str | Msg", lang: str) -> str:
    return value.render(lang) if isinstance(value, Msg) else value


CATALOG: dict[str, dict[str, str]] = {
    # Copywriter and Brand Guardian
    "copy.writing": {"az": "3 variant yazır (AZ + RU)", "ru": "Пишет 3 варианта (AZ + RU)", "en": "Writing 3 options (AZ + RU)", "fa": "در حال نوشتن ۳ گزینه (آذری + روسی)"},
    "copy.ready": {"az": "3 variant hazırdır", "ru": "3 варианта готовы", "en": "3 options ready", "fa": "۳ گزینه آماده است"},
    "copy.fixing": {"az": "Nəzarətçinin qeydlərinə görə {n} variantı düzəldir", "ru": "Исправляет {n} вариант(а) по замечаниям", "en": "Fixing {n} option(s) from the Guardian's notes", "fa": "اصلاح {n} گزینه طبق یادداشت‌های نگهبان"},
    "copy.fixed": {"az": "Düzəliş hazırdır", "ru": "Исправление готово", "en": "Fix ready", "fa": "اصلاح آماده است"},
    "copy.failed": {"az": "Mətn yazıla bilmədi: {error}", "ru": "Не удалось написать текст: {error}", "en": "The text could not be written: {error}", "fa": "متن نوشته نشد: {error}"},
    "copy.crashed": {"az": "Mətn yazılarkən gözlənilməz xəta baş verdi.", "ru": "При написании текста произошла неожиданная ошибка.", "en": "An unexpected error happened while writing.", "fa": "هنگام نوشتن متن خطای غیرمنتظره‌ای رخ داد."},
    "guard.checking": {"az": "Dil, qadağan sözlər və iddialar yoxlanılır", "ru": "Проверяет язык, запрещённые слова и утверждения", "en": "Checking language, banned words and claims", "fa": "بررسی زبان، کلمات ممنوع و ادعاها"},
    "guard.result": {"az": "{ok}/3 variant qaydasındadır", "ru": "{ok}/3 вариантов в порядке", "en": "{ok}/3 options pass", "fa": "{ok} از ۳ گزینه درست است"},
    "guard.rechecking": {"az": "Düzəlişlər yoxlanılır", "ru": "Проверяет исправления", "en": "Checking the fixes", "fa": "بررسی اصلاحات"},
    "guard.done": {"az": "Yoxlama bitdi", "ru": "Проверка завершена", "en": "Check finished", "fa": "بررسی تمام شد"},
    "guard.pass": {"az": "Qaydasındadır", "ru": "В порядке", "en": "Passes", "fa": "درست است"},
    "guard.notes": {"az": "Qeydləri var", "ru": "Есть замечания", "en": "Has notes", "fa": "یادداشت دارد"},
    "revise.start": {"az": "Düzəliş edir: {instruction}", "ru": "Вносит правку: {instruction}", "en": "Revising: {instruction}", "fa": "در حال اصلاح: {instruction}"},
    "revise.done": {"az": "Düzəltdim: “{instruction}”.{note} Təsdiqləyirsiniz?", "ru": "Исправил: «{instruction}».{note} Одобряете?", "en": "Done: “{instruction}”.{note} Do you approve?", "fa": "اصلاح شد: «{instruction}».{note} تأیید می‌کنید؟"},
    "revise.note": {"az": " Nəzarətçinin qeydləri var, baxın.", "ru": " У хранителя бренда есть замечания, посмотрите.", "en": " The Guardian has notes, please look.", "fa": " نگهبان برند یادداشت دارد، لطفاً ببینید."},
    "revise.failed": {"az": "Düzəliş alınmadı: {error}", "ru": "Правка не удалась: {error}", "en": "The revision failed: {error}", "fa": "اصلاح انجام نشد: {error}"},
    # Photos and posts
    "photo.analysing": {"az": "Şəkli təhlil edir", "ru": "Анализирует фото", "en": "Analysing a photo", "fa": "در حال تحلیل عکس"},
    "photo.done": {"az": "Təhlil edildi: {title}", "ru": "Проанализировано: {title}", "en": "Analysed: {title}", "fa": "تحلیل شد: {title}"},
    "photo.failed": {"az": "Təhlil alınmadı: {error}", "ru": "Анализ не удался: {error}", "en": "Analysis failed: {error}", "fa": "تحلیل انجام نشد: {error}"},
    "photos.picked": {"az": "{n} şəkil seçildi: {name}", "ru": "Выбрано фото: {n} — {name}", "en": "{n} photo(s) picked: {name}", "fa": "{n} عکس انتخاب شد: {name}"},
    "post.kind.carousel": {"az": "karusel", "ru": "карусель", "en": "carousel", "fa": "کاروسل"},
    "post.kind.single": {"az": "post", "ru": "пост", "en": "post", "fa": "پست"},
    "post.ready": {"az": "Post hazırdır və sizin təsdiqinizi gözləyir. {when} Təsdiqləyin və ya nəyi dəyişmək lazım olduğunu yazın.", "ru": "Пост готов и ждёт вашего одобрения. {when} Одобрите или напишите, что изменить.", "en": "The post is ready and waits for your approval. {when} Approve it or write what to change.", "fa": "پست آماده است و منتظر تأیید شماست. {when} تأیید کنید یا بنویسید چه چیزی تغییر کند."},
    "post.when_at": {"az": "Paylaşım vaxtı: {when} (Bakı).", "ru": "Время публикации: {when} (Баку).", "en": "Publishing time: {when} (Baku).", "fa": "زمان انتشار: {when} (باکو)."},
    "post.when_now": {"az": "Təsdiqdən dərhal sonra paylaşılacaq.", "ru": "Будет опубликован сразу после одобрения.", "en": "It goes out right after approval.", "fa": "بلافاصله بعد از تأیید منتشر می‌شود."},
    "publish.start": {"az": "{channels} paylaşılır", "ru": "Публикуется: {channels}", "en": "Publishing to {channels}", "fa": "در حال انتشار در {channels}"},
    "publish.done_event": {"az": "Paylaşıldı", "ru": "Опубликовано", "en": "Published", "fa": "منتشر شد"},
    "publish.done": {"az": "Paylaşıldı. {links}", "ru": "Опубликовано. {links}", "en": "Published. {links}", "fa": "منتشر شد. {links}"},
    "publish.failed_event": {"az": "Paylaşım alınmadı: {errors}", "ru": "Публикация не удалась: {errors}", "en": "Publishing failed: {errors}", "fa": "انتشار انجام نشد: {errors}"},
    "publish.partial": {"az": "Paylaşım tam alınmadı: {errors}.{done} Yenidən cəhd etmək üçün təsdiqləyin.", "ru": "Публикация прошла не полностью: {errors}.{done} Одобрите, чтобы повторить.", "en": "Publishing did not fully work: {errors}.{done} Approve again to retry.", "fa": "انتشار کامل نشد: {errors}.{done} برای تلاش دوباره تأیید کنید."},
    "publish.partial_done": {"az": " Paylaşılan: {links}.", "ru": " Опубликовано: {links}.", "en": " Published: {links}.", "fa": " منتشرشده: {links}."},
    "schedule.event": {"az": "{when} üçün planlaşdırıldı", "ru": "Запланировано на {when}", "en": "Scheduled for {when}", "fa": "برای {when} زمان‌بندی شد"},
    "schedule.say": {"az": "Təsdiqləndi. {when}-də (Bakı) avtomatik paylaşılacaq.", "ru": "Одобрено. Будет опубликовано автоматически {when} (Баку).", "en": "Approved. It goes out automatically at {when} (Baku).", "fa": "تأیید شد. {when} (به وقت باکو) خودکار منتشر می‌شود."},
    # Team Lead
    "lead.no_key": {"az": "Komanda hələ qurulmayıb (AI açarı yoxdur).", "ru": "Команда ещё не настроена (нет ключа AI).", "en": "The team is not set up yet (no AI key).", "fa": "تیم هنوز راه‌اندازی نشده است (کلید AI وجود ندارد)."},
    "lead.reading": {"az": "Mesajı oxuyur", "ru": "Читает сообщение", "en": "Reading the message", "fa": "در حال خواندن پیام"},
    "lead.failed_event": {"az": "Cavab verə bilmədi: {error}", "ru": "Не смог ответить: {error}", "en": "Could not answer: {error}", "fa": "نتوانست پاسخ دهد: {error}"},
    "lead.unavailable": {"az": "Hazırda cavab verə bilmirəm ({error}). Bir az sonra yenidən yazın.", "ru": "Сейчас не могу ответить ({error}). Напишите чуть позже.", "en": "I can't answer right now ({error}). Please write again a bit later.", "fa": "الان نمی‌توانم پاسخ دهم ({error}). کمی بعد دوباره بنویسید."},
    "lead.started": {"az": "{n} tapşırıq başladıldı", "ru": "Запущено задач: {n}", "en": "{n} task(s) started", "fa": "{n} کار شروع شد"},
    "lead.answered": {"az": "Cavab verdi", "ru": "Ответил", "en": "Answered", "fa": "پاسخ داد"},
    "lead.not_allowed": {"az": "Sizin rolunuz tapşırıq verməyə icazə vermir; yalnız sual verə bilərsiniz.", "ru": "Ваша роль не позволяет давать задания; можно только задавать вопросы.", "en": "Your role can't give the team work; you can only ask questions.", "fa": "نقش شما اجازه دادن کار به تیم را نمی‌دهد؛ فقط می‌توانید سؤال بپرسید."},
    "lead.action_failed": {"az": "Alınmadı: {error}.", "ru": "Не получилось: {error}.", "en": "That didn't work: {error}.", "fa": "انجام نشد: {error}."},
    # Market research
    "research.title": {"az": "Bazar araşdırması · {day}", "ru": "Исследование рынка · {day}", "en": "Market research · {day}", "fa": "تحقیق بازار · {day}"},
    "research.start": {"az": "Bazarı araşdırır: rəqiblər, müştərilər, internet", "ru": "Исследует рынок: конкуренты, клиенты, интернет", "en": "Researching the market: competitors, customers, web", "fa": "در حال تحقیق بازار: رقبا، مشتریان، اینترنت"},
    "research.done": {"az": "Bazar hesabatı hazırdır: {headline}", "ru": "Отчёт о рынке готов: {headline}", "en": "Market report ready: {headline}", "fa": "گزارش بازار آماده است: {headline}"},
    "research.failed": {"az": "Araşdırma alınmadı: {error}", "ru": "Исследование не удалось: {error}", "en": "Research failed: {error}", "fa": "تحقیق انجام نشد: {error}"},
    "step.competitors": {"az": "{seen}/{total} rəqib görünür", "ru": "Видно конкурентов: {seen}/{total}", "en": "{seen}/{total} competitors visible", "fa": "{seen} از {total} رقیب دیده شد"},
    "step.own_page": {"az": "{posts} post · {comments} şərh", "ru": "{posts} постов · {comments} комм.", "en": "{posts} posts · {comments} comments", "fa": "{posts} پست · {comments} کامنت"},
    "step.no_instagram": {"az": "Instagram qoşulmayıb", "ru": "Instagram не подключён", "en": "Instagram is not connected", "fa": "اینستاگرام وصل نیست"},
    "step.web": {"az": "{searches} axtarış · {sources} mənbə{found}", "ru": "{searches} поиск. · {sources} источн.{found}", "en": "{searches} searches · {sources} sources{found}", "fa": "{searches} جستجو · {sources} منبع{found}"},
    "step.web_found": {"az": " · {n} yeni rəqib", "ru": " · новых конкурентов: {n}", "en": " · {n} new competitor(s)", "fa": " · {n} رقیب جدید"},
    "step.analyse": {"az": "{images} şəkil · {ideas} ideya", "ru": "{images} фото · {ideas} идей", "en": "{images} images · {ideas} ideas", "fa": "{images} عکس · {ideas} ایده"},
    # Morning report
    "briefing.title": {"az": "Səhər hesabatı · {day}", "ru": "Утренний отчёт · {day}", "en": "Morning report · {day}", "fa": "گزارش صبح · {day}"},
    "briefing.start": {"az": "Səhər hesabatını hazırlayır", "ru": "Готовит утренний отчёт", "en": "Preparing the morning report", "fa": "در حال آماده کردن گزارش صبح"},
    "briefing.done": {"az": "Səhər hesabatı göndərildi", "ru": "Утренний отчёт отправлен", "en": "Morning report sent", "fa": "گزارش صبح ارسال شد"},
    "briefing.failed": {"az": "Səhər hesabatı alınmadı: {error}", "ru": "Утренний отчёт не удался: {error}", "en": "The morning report failed: {error}", "fa": "گزارش صبح انجام نشد: {error}"},
    "step.facts": {"az": "{written} post yazılıb · {waiting} təsdiq gözləyir", "ru": "Написано постов: {written} · ждут одобрения: {waiting}", "en": "{written} posts written · {waiting} waiting for approval", "fa": "{written} پست نوشته شد · {waiting} منتظر تأیید"},
    "step.no_market": {"az": "Bu gün bazar hesabatı yoxdur", "ru": "Сегодня нет отчёта о рынке", "en": "No market report today", "fa": "امروز گزارش بازار وجود ندارد"},
    "step.plan": {"az": "{plan} plan · {suggestions} təklif", "ru": "План: {plan} · предложений: {suggestions}", "en": "{plan} plan items · {suggestions} suggestions", "fa": "{plan} برنامه · {suggestions} پیشنهاد"},
    # Team meeting
    "meeting.title": {"az": "Komanda iclası · {day}", "ru": "Совещание команды · {day}", "en": "Team meeting · {day}", "fa": "جلسه تیم · {day}"},
    "meeting.start": {"az": "Komanda iclası: gündəm hazırlanır", "ru": "Совещание: готовится повестка", "en": "Team meeting: setting the agenda", "fa": "جلسه تیم: در حال تنظیم دستور جلسه"},
    "meeting.said": {"az": "İclasda: {answer}", "ru": "На совещании: {answer}", "en": "In the meeting: {answer}", "fa": "در جلسه: {answer}"},
    "meeting.done": {"az": "İclas bitdi: nəticələr sizə göndərildi", "ru": "Совещание завершено: итоги отправлены вам", "en": "Meeting finished: the outcome was sent to you", "fa": "جلسه تمام شد: نتیجه برای شما ارسال شد"},
    "meeting.failed": {"az": "İclas alınmadı: {error}", "ru": "Совещание не удалось: {error}", "en": "The meeting failed: {error}", "fa": "جلسه انجام نشد: {error}"},
    "step.decided": {"az": "{goals} hədəf · {plan} post planı", "ru": "Целей: {goals} · постов в плане: {plan}", "en": "{goals} goals · {plan} planned posts", "fa": "{goals} هدف · {plan} پست در برنامه"},
}
