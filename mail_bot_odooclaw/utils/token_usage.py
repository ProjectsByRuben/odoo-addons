"""Render trusted numeric model telemetry without putting it in agent history."""
from markupsafe import Markup, escape


def token_usage_footer(usage):
    """Missing/invalid telemetry is unknown, never an invented token count."""
    valid = isinstance(usage, dict)
    keys = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens', 'model_calls')
    if valid:
        valid = all(type(usage.get(key)) is int and 0 <= usage[key] <= 10**12 for key in keys)
        valid = valid and type(usage.get('complete')) is bool
    if valid:
        valid = (usage['total_tokens'] == usage['input_tokens'] + usage['output_tokens']
                 and usage['cached_input_tokens'] <= usage['input_tokens'])
    if not valid:
        label = 'Tokens: no disponibles'
        detail = 'El proveedor no ha comunicado el consumo de esta solicitud.'
    else:
        def number(value):
            return format(value, ',').replace(',', '.')
        label = 'Tokens: ' + number(usage['total_tokens'])
        if not usage['complete']:
            label += ' registrados · consumo parcial'
        detail = ('Entrada: %s · Salida: %s · Entrada en caché: %s (incluida en la entrada). '
                  'Llamadas al modelo: %s. Consumo de esta solicitud, sumando sus pasos.' %
                  (number(usage['input_tokens']), number(usage['output_tokens']),
                   number(usage['cached_input_tokens']), number(usage['model_calls'])))
        if not usage['complete']:
            detail += ' Falta el consumo de alguna llamada; el total real puede ser mayor.'
    return Markup('<div class="o_odooclaw_token_usage" style="margin-top:10px;padding-top:6px;'
                  'border-top:1px solid #e5e7eb;font-size:11px;color:#6b7280;" '
                  'title="%s">%s</div>') % (escape(detail), escape(label))
