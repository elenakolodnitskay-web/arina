from core.finance import parse_finance_message
from db.models import Transaction, TransactionType, User
from db.session import SessionLocal


def _format_amount(amount: float) -> str:
    """Показывает сумму без лишних нулей, но не округляя — иначе пользователю
    показывали бы "200 ₽" для потраченных 199.99, хотя в БД сохранено точное
    значение (несовпадение между тем, что видит пользователь, и тем, что записано).
    """
    formatted = f"{amount:.2f}".rstrip("0").rstrip(".")
    return formatted or "0"


async def record_finance_message(user_id: int, text: str) -> str | None:
    """Разбирает сообщение о трате/поступлении, новом балансе или пороге для
    предупреждения о низком балансе — сохраняет и возвращает текст ответа.

    Возвращает None, если модель не смогла разобрать сумму/тип сообщения — в этом
    случае ничего не сохраняется.
    """
    parsed = await parse_finance_message(text)
    if parsed is None:
        return None

    with SessionLocal() as session:
        user = session.get(User, user_id)

        if parsed.kind == "balance":
            user.balance = parsed.amount
            session.commit()
            reply = f"Записала баланс: {_format_amount(parsed.amount)} ₽."
            if user.low_balance_threshold is not None and user.balance < user.low_balance_threshold:
                reply += (
                    f"\n⚠️ Баланс ниже порога {_format_amount(user.low_balance_threshold)} ₽ — "
                    "стоит быть внимательнее с тратами."
                )
            return reply

        if parsed.kind == "threshold":
            user.low_balance_threshold = parsed.amount
            session.commit()
            return f"Буду предупреждать, если баланс станет меньше {_format_amount(parsed.amount)} ₽."

        if parsed.transaction_type not in ("expense", "income"):
            return None

        transaction_type = TransactionType(parsed.transaction_type)
        transaction = Transaction(
            user_id=user_id,
            amount=parsed.amount,
            transaction_type=transaction_type,
            description=parsed.category,
        )
        session.add(transaction)
        session.commit()

        label = "расход" if transaction_type == TransactionType.expense else "поступление"
        category_part = f" ({parsed.category})" if parsed.category else ""
        return f"Записала {label}: {_format_amount(parsed.amount)} ₽{category_part}."
