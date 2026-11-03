"""Conservative checks for explicitly labelled source amounts, independent of LLM roles."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re


TOTAL_LABEL = re.compile(
    r"(?<![A-Z])(?:GRAND\s+TOTAL|TOTAL\s+CHARGES(?:\s+TO\s+BE\s+PAID)?|"
    r"TOTAL\s+AMOUNT|INVOICE\s+TOTAL|TOTAL\s+DUE|TOTAL(?=\s*(?:$|[:：=\d$€¥]|USD|CNY|RMB|EUR|GBP|HKD|JPY|CAD|AUD)))(?![A-Z])|"
    r"总计|总金额|费用合计|应付总额|合计金额", re.I)
NON_LINE_LABEL = re.compile(
    r"(?<![A-Z])(?:SUB\s*TOTAL|BALANCE\s+DUE|AMOUNT\s+PAID|PAID\s+AMOUNT|"
    r"UNIT\s+PRICE|EXCHANGE\s+RATE|RATE)(?![A-Z])|小计|余额|已付|单价|汇率", re.I)
NUMBER = re.compile(r"(?<![A-Z\d-])[-+]?\d[\d,]*(?:\.\d+)?(?![A-Z\d])", re.I)
CURRENCY = re.compile(r"(?<![A-Z])(?:USD|CNY|RMB|EUR|GBP|HKD|JPY|CAD|AUD)(?![A-Z])", re.I)


def _labels(text):
    # Weight/unit columns can be glued to the following total label by PDF text extraction.
    text = re.sub(r"\bSUB\s+TOTAL\b", "SUBTOTAL", text, flags=re.I)
    return re.sub(r"(LBS|KGS)(?=TOTAL\s+CHARGES)", r"\1 ", text, flags=re.I)


def _clean(text):
    # Native PDF extraction can join 245.0000 and 10/19/2026 with no whitespace.
    text = re.sub(r"(\d+\.\d{2,8}?)(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/((?:19|20)\d{2})",
                  r"\1 \2/\3/\4", str(text).replace("−", "-"))
    text = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}-\d{1,2}-\d{1,2}\b", " ", text)
    return re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?\b", " ", text, flags=re.I)


def _numbers(text):
    result = []
    for match in NUMBER.finditer(_clean(text)):
        try:
            result.append(Decimal(match.group().replace(",", "")))
        except InvalidOperation:
            continue
    return result


def _fee_tail(text):
    # Revision prose in a plain-text block is not part of the preceding fee table row.
    return re.split(r"(?:please\s+)?\b(?:revise|correct|amend|change)\b|修订|更正|改为", text, maxsplit=1, flags=re.I)[0]


def _debit_credit_header(blocks, index):
    page = blocks[index].get("page")
    return any(b.get("page") == page and re.search(r"DEBIT\s*\(\+\).*CREDIT\s*\(-\)", b.get("text", ""), re.I)
               for b in blocks[:index])


def _single_side(debit, credit):
    values = {Decimal(value.replace(",", "")) for value in (debit, credit) if value is not None}
    nonzero = values - {Decimal("0")}
    return next(iter(nonzero)) if len(nonzero) == 1 else Decimal("0") if values == {Decimal("0")} else None


def _amount_cell(evidence, sources):
    """Resolve known source table headers, not model-supplied column metadata."""
    for source in sources:
        if evidence.source_id and source.get("source_id") != evidence.source_id:
            continue
        if not evidence.source_id and source.get("source_file") != evidence.source_file:
            continue
        blocks = source.get("blocks", [])
        for index, block in enumerate(blocks):
            if evidence.block_id != block.get("block_id"):
                continue
            if _debit_credit_header(blocks, index):
                number = r"([-+]?\d[\d,]*(?:\.\d+)?)"
                row = re.search(r"(?:^|\s)-\s+" + number + r"\s+" + number + r"\s+[PC]\s+" + number
                                + r"(?:\s+" + number + r")?\s*$", block.get("text", ""), re.I)
                if row:
                    return _single_side(row.group(3), row.group(4))
            if "|" not in block.get("text", ""):
                continue
            cells = [part.strip() for part in block["text"].strip().strip("|").split("|")]
            for header in reversed(blocks[max(0, index - 5):index]):
                if header.get("page") != block.get("page"):
                    continue
                titles = [part.strip().casefold() for part in header.get("text", "").strip().strip("|").split("|")]
                if len(cells) != len(titles):
                    continue
                for column, title in enumerate(titles):
                    if title in {"amount", "line amount", "charge amount", "金额", "明细金额", "原币金额"}:
                        values = _numbers(cells[column])
                        return values[0] if len(values) == 1 else None
    return None


def _block_text(evidence, sources):
    for source in sources:
        if evidence.source_id and evidence.source_id != source.get("source_id"):
            continue
        if not evidence.source_id and evidence.source_file != source.get("source_file"):
            continue
        for block in source.get("blocks", []):
            if evidence.block_id and evidence.block_id == block.get("block_id"):
                return block.get("text", "")
    return evidence.original_text


def line_amount_evidence(evidence, decision, sources):
    """A field_name supplied by the model cannot turn a TOTAL row into a fee row."""
    quote = evidence.original_text
    actual = _block_text(evidence, sources)
    name = " ".join(decision.charge_details.original_name.casefold().split())
    # A single text block may contain both a genuine fee quote and a later total.
    for text in (_labels(quote), _labels(actual)):
        label = TOTAL_LABEL.search(text) or NON_LINE_LABEL.search(text)
        if not label:
            continue
        prefix = text[:label.start()]
        if (name and name in " ".join(prefix.casefold().split())
                and decision.charge_details.amount in _numbers(prefix)):
            continue
        return False
    text = " ".join(actual.split())
    position = text.casefold().find(name)
    tail = _fee_tail(text[position + len(name):] if name and position >= 0 else text)
    label = TOTAL_LABEL.search(_labels(tail)) or NON_LINE_LABEL.search(tail)
    if label:
        tail = tail[:label.start()]
    if len(set(_numbers(tail))) > 1:
        return _amount_cell(evidence, sources) == decision.charge_details.amount
    return True


def _related_pages(decision, source):
    pages = {e.page for e in decision.evidence if e.page is not None
             and (e.source_id == source.get("source_id") or
                  (not e.source_id and e.source_file == source.get("source_file")))}
    ids = {e.block_id for e in decision.evidence if e.block_id}
    pages.update(b["page"] for b in source.get("blocks", []) if b.get("block_id") in ids and b.get("page") is not None)
    return pages


def source_totals(source, pages=None):
    """Find explicit totals only; never manufacture a total by adding fee rows."""
    blocks = source.get("blocks") or [{"text": source.get("content", "")}]
    found = []
    for index, block in enumerate(blocks):
        if pages and block.get("page") is not None and block["page"] not in pages:
            continue
        text = _labels(block.get("text", ""))
        label = TOTAL_LABEL.search(text)
        if not label:
            continue
        tail = text[label.end():]
        next_label = NON_LINE_LABEL.search(tail)
        if next_label:
            tail = tail[:next_label.start()]
        values = _numbers(tail)
        if len(values) == 2 and _debit_credit_header(blocks, index):
            single_side = _single_side(str(values[0]), str(values[1]))
            if single_side is not None:
                values = [single_side]
        currency_match = CURRENCY.search(tail)
        if not values:
            # Some PDFs split the label, currency and value into adjacent rows.
            for following in blocks[index + 1:index + 4]:
                if following.get("page") != block.get("page"):
                    break
                part = following.get("text", "").strip()
                if re.search(r"[A-Za-z]", CURRENCY.sub("", part)):
                    break
                if not currency_match:
                    currency_match = CURRENCY.search(part)
                values = _numbers(part)
                if values:
                    break
        found.append({"amount": values[0] if len(set(values)) == 1 else None,
                      "ambiguous": len(set(values)) > 1,
                      "currency": currency_match.group().upper() if currency_match else None,
                      "block_id": block.get("block_id"), "page": block.get("page")})
    return found


def source_line_amounts(decision, source, pages=None):
    """Use only unambiguous fee-name rows; do not guess columns in a flattened table."""
    name = " ".join(decision.charge_details.original_name.casefold().split())
    blocks = source.get("blocks", [])
    found = set()
    for index, block in enumerate(blocks):
        if pages and block.get("page") is not None and block["page"] not in pages:
            continue
        text = " ".join(block.get("text", "").split())
        position = text.casefold().find(name)
        if not name or position < 0:
            continue
        tail = _fee_tail(text[position + len(name):])
        label = TOTAL_LABEL.search(_labels(tail)) or NON_LINE_LABEL.search(tail)
        if label:
            tail = tail[:label.start()]
        values = set(_numbers(tail))
        if not values:
            for following in blocks[index + 1:index + 3]:
                if following.get("page") != block.get("page"):
                    break
                part = following.get("text", "").strip()
                if re.search(r"[A-Za-z]", CURRENCY.sub("", part)):
                    break
                values = set(_numbers(part))
                if values:
                    break
        if len(values) == 1:
            found.update(values)
    return found


def validate_source_totals(decisions, sources):
    errors, groups = [], defaultdict(list)
    for decision in decisions:
        for source in sources:
            if any((e.source_id and e.source_id == source.get("source_id")) or
                   (not e.source_id and e.source_file == source.get("source_file")) for e in decision.evidence):
                key = (source.get("source_id") or source.get("source_file"),
                       decision.document_info.document_number, decision.transaction_party.issuer)
                groups[key].append((decision, source))
    for group_key, rows in groups.items():
        source = rows[0][1]
        pages = set().union(*(_related_pages(d, source) for d, _ in rows))
        siblings = [(key, value) for key, value in groups.items() if key[0] == group_key[0]]
        if len(siblings) == 1:
            pages = None  # A document total may be on a later page with no fee evidence.
        else:
            starts = {key: min(set().union(*(_related_pages(d, source) for d, _ in group)))
                      for key, group in siblings if any(_related_pages(d, source) for d, _ in group)}
            if len(starts) == len(siblings) and len(set(starts.values())) == len(starts):
                start = starts[group_key]
                stop = min((page for page in starts.values() if page > start), default=float("inf"))
                pages = {b["page"] for b in source.get("blocks", []) if b.get("page") is not None
                         and start <= b["page"] < stop}
        for decision, _ in rows:
            observed_lines = source_line_amounts(decision, source, _related_pages(decision, source))
            if observed_lines and decision.charge_details.amount not in observed_lines:
                errors.append(f"来源费用明细金额 {sorted(map(str, observed_lines))} 与拟入账金额 {decision.charge_details.amount} 不一致；需核对原单")
        observed = source_totals(source, pages)
        if not observed:
            continue
        amounts = {item["amount"] for item in observed if item["amount"] is not None}
        if any(item.get("ambiguous") for item in observed):
            errors.append("原文总额行包含多个金额，币种或列角色无法唯一确定；需补提取或人工核对")
            continue
        if not amounts:
            errors.append("原文存在总额标签，但对应金额无法确定；需要补提取或人工核对")
            continue
        if len(amounts) != 1:
            errors.append("关联来源存在多个不同总额，无法唯一绑定当前单据；需复核")
            continue
        source_total = next(iter(amounts))
        stated = {d.document_info.document_total for d, _ in rows if d.document_info.document_total is not None}
        if not stated:
            errors.append(f"原文明示总额 {source_total}，模型未提取单据总额，不能跳过核对")
        elif stated != {source_total}:
            errors.append(f"模型单据总额 {sorted(map(str, stated))} 与来源总额 {source_total} 不一致")
        currencies = {d.charge_details.currency for d, _ in rows}
        explicit_currencies = {item["currency"] for item in observed if item["currency"]}
        if len(currencies) != 1 or None in currencies or (explicit_currencies and currencies != explicit_currencies):
            errors.append("原文总额与明细币种不能直接核对")
            continue
        calculated = sum((d.charge_details.amount for d, _ in rows), Decimal("0"))
        if calculated != source_total:
            errors.append(f"单据明细合计 {calculated} {next(iter(currencies))}，原文总额 {source_total}，差额 {calculated - source_total}；整单待复核")
    return list(dict.fromkeys(errors))
