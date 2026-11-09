# Petición original

Fecha: 2026-11-09, después de validar la Fase 57 en INT (v57).

Miguel pide, con sus palabras:

- Quitar "As billed", porque "aquí sólo trabajamos con cuentas que existan".
- En Options, Freelance, poder reordenar las cuentas y los "income sources" con un botón de puntitos que se arrastra, e investigar qué otras cosas podrían ser reordenables.
- Una excepción a que todo se guarde al escribir, para los payouts, porque hay "demasiadas monedas volando por ahí". En su lugar, un botón de confirmar que sea un estampido del sello de Kronos.
- Hacerlo más genérico, para más público: a cada proyecto freelance se le pueden configurar 1, 2, 3 o hasta 4 cuentas. El primer pago se hace en una moneda y luego esa cuenta transfiere a la segunda, como en su caso, de Stripe a Deutsche Bank. La mayoría de la gente solo recibirá en una cuenta.
- La cuenta primera pone los números sobre la segunda, tercera y cuarta. Un número escrito en una cuenta es fijo, modifica en cascada las siguientes y ya no se ve afectado por los de otras cuentas. El importe final del payout es el de la última cuenta.
- Todas las cajas de texto de las cuentas de un payout llevan una pequeña "X" de limpiar.
- Las cuentas se asignan a un proyecto arrastrándolas a cajas en outline discontinuo, en un tono apagado, a la derecha del nombre y del ratio. La posición de la caja es la posición en la cadena. Él arrastraría Stripe a la primera caja de Coding Behaviors y Deutsche Bank a la segunda.
- En el móvil, mantener pulsado un poco antes de poder arrastrar, para evitar arrastres accidentales.

# Evidencia comprobada antes de la entrevista

Comprobado leyendo el repositorio en la rama `master` (v57):

- Cuentas (`Account`) y fuentes (`IncomeSource`) no tienen columna de orden. Tampoco las plantillas de día (`Template`).
- Las listas de Settings son: fuentes, cuentas, plantillas, calendario de objetivos y festivos. Las dos últimas van por fecha, así que el reordenado solo tiene sentido en las tres primeras.
- Ya hay arrastres propios con `pointerdown` en `backend/static/app.js`, y `touch-action` en la barra del día. No hay ninguna librería de arrastre.
- La Fase 57 guarda lo enviado en `sent_amount`, `sent_currency` y `from_account_id`, y lo que llegó en `amount`, `currency` y `account_id`. Las cuentas tienen `role`, y las fuentes `default_from_account_id` y `default_account_id`.
