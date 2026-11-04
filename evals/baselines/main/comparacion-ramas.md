# Comparación de ramas contra el baseline de `main`

*2026-11-04. Mismas 330 personas (semilla 7) que `evals/baselines/main/`. Mismos modelos. Corridas con el harness de `claude/loving-davinci-otqdgy` copiado sobre cada rama.*

**Ojo con el ruido.** El cliente simulado no responde igual en cada corrida: una misma persona puede pasar de 100 a 22 puntos sin que cambie nada. El IC del overall es ±2. Diferencias de menos de ~2 puntos en el overall, o de menos de ~5 pp en un código, no se pueden distinguir del azar. La corrida de ruido (main dos veces) quedó pendiente por presupuesto. Los códigos regex son más confiables que los del juez.

Se cortaron por presupuesto, sin resultado: `amazing-dirac-i24hih` (productización) y `gracious-cray-lb4lwk` (hoja de Google).

## `claude/sharp-clarke-suo0f3 (base de conocimiento)`



Overall: **-0.12** · costo por conversación: -0.00 USD

| dimensión | Δ |
|---|---|
| humanness | -0.14 |
| accuracy | +0.07 |
| rules | -0.01 |
| sales | 0.00 |
| language | +0.09 |
| length | 0.00 |

| resultado | Δ |
|---|---|
| email_requested | +1.2 pp |
| client_gave_email | -1.2 pp |
| email_captured | -1.2 pp |
| videocall_offered | 0.0 pp |
| paused | -0.3 pp |

| código | baseline | ahora | Δ |
|---|---|---|---|
| INVENTED_PRICE | 13.6% | 9.4% | -4.2 pp |
| SHORT_PROGRAM_TO_INEXPERIENCED | 31.2% | 34.5% | +3.3 pp |
| WRONG_FACT | 4.5% | 2.1% | -2.4 pp |
| ROBOTIC_TONE | 30.3% | 32.7% | +2.4 pp |
| TOO_LONG | 25.1% | 22.7% | -2.4 pp |
| EMPTY_REPLY | 13.9% | 16.1% | +2.1 pp |
| EMAIL_ASKED_AFTER_GIVEN | 20.6% | 22.7% | +2.1 pp |
| CONFIRMS_AVAILABILITY | 22.7% | 20.9% | -1.8 pp |
| ASESOR_HUMANO | 1.8% | 3.6% | +1.8 pp |
| OFF_SEASON_NOT_EXPLAINED | 3.9% | 2.4% | -1.5 pp |
| IDENTICAL_REPLY | 16.1% | 14.5% | -1.5 pp |
| ASKS_WANT_HUMAN | 1.5% | 0.3% | -1.2 pp |
| INVENTED_DISCOUNT | 2.7% | 3.9% | +1.2 pp |
| SELLS_LOOSE_LOGISTICS | 5.1% | 3.9% | -1.2 pp |
| REPEATED_GREETING | 4.2% | 5.5% | +1.2 pp |
| NO_VIDEOCALL_FOR_BUYER | 25.4% | 24.2% | -1.2 pp |
| FAQ_ONLY_PRICE | 0.3% | 1.2% | +0.9 pp |
| MENTIONS_DOCS | 1.8% | 2.7% | +0.9 pp |
| CONFIRMS_BOOKING | 1.2% | 2.1% | +0.9 pp |
| LANGUAGE_DRIFT | 17.3% | 18.2% | +0.9 pp |


## `claude/gracious-fermi-gwx1jf-saludo (voz humana; incluye -burbujas, -nombre y -usted)`



Overall: **-0.25** · costo por conversación: +0.00 USD

| dimensión | Δ |
|---|---|
| humanness | -0.03 |
| accuracy | -0.01 |
| rules | -0.01 |
| sales | -0.06 |
| language | +0.15 |
| length | -0.16 |

| resultado | Δ |
|---|---|
| email_requested | -15.4 pp |
| client_gave_email | -0.3 pp |
| email_captured | -0.3 pp |
| videocall_offered | +2.5 pp |
| paused | +3.7 pp |

| código | baseline | ahora | Δ |
|---|---|---|---|
| SHORT_PROGRAM_TO_INEXPERIENCED | 31.2% | 37.0% | +5.8 pp |
| UNHELPFUL_DEFLECTION | 46.1% | 40.6% | -5.5 pp |
| REPEATED_GREETING | 4.2% | 9.4% | +5.1 pp |
| EMAIL_ASKED_AFTER_GIVEN | 20.6% | 25.8% | +5.1 pp |
| VOSEO_WITH_USTED | 23.3% | 18.5% | -4.9 pp |
| NO_QUALIFICATION | 30.6% | 34.5% | +3.9 pp |
| PHANTOM_EMAIL | 2.7% | 5.8% | +3.0 pp |
| IDENTICAL_REPLY | 16.1% | 18.8% | +2.7 pp |
| ROBOTIC_TONE | 30.3% | 33.0% | +2.7 pp |
| MENTIONS_DOCS | 1.8% | 4.2% | +2.4 pp |
| EMAIL_ASKED_TWICE | 5.8% | 7.9% | +2.1 pp |
| TOO_LONG | 25.1% | 27.0% | +1.8 pp |
| HALLUCINATED_FACT | 8.2% | 10.0% | +1.8 pp |
| INVENTED_PRICE | 13.6% | 12.1% | -1.5 pp |
| INCLUDES_EVERYTHING | 19.7% | 21.2% | +1.5 pp |
| CONFIRMS_BOOKING | 1.2% | 2.4% | +1.2 pp |
| INSURANCE_INCLUDED | 1.8% | 0.6% | -1.2 pp |
| ASESOR_HUMANO | 1.8% | 3.0% | +1.2 pp |
| SELLS_LOOSE_LOGISTICS | 5.1% | 3.9% | -1.2 pp |
| MEDICAL_ADVICE | 8.8% | 7.6% | -1.2 pp |


