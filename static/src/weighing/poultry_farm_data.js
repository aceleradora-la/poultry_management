import { Component, useState, useRef, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { formatNum, parseNum, selectOnFocus } from "./poultry_number_input";

const CLOSE_MODEL = "poultry.coop.close";

/**
 * OF de Huevo sin Clasificar desde el celular: el ÚNICO lugar donde se cargan las aves
 * muertas y los consumos del día. La OF la crea el Cierre de Galpón y la oficina la marca
 * Hecha al otro día; hasta entonces el operador le carga las aves muertas y la cantidad
 * consumida de cada componente (alimento, agua, lo que tenga la lista).
 */
export class PoultryFarmData extends Component {
    static template = "poultry_management.PoultryFarmData";
    static props = { onHome: Function };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.selectOnFocus = selectOnFocus;
        this.formRef = useRef("form");
        this.state = useState({
            screen: "list", // list | order
            orders: [],
            order: null, // datos de la OF (poultry.coop.close.poultry_mobile_data)
            form: { dead: "", note: "", lines: [] }, // lines: [{ id, product, uom, planned, type, isKg, picked, unit, qty }]
            busy: false,
        });
        onWillStart(() => this.loadList());
    }

    // ------------------------------------------------------------------
    // Formato
    // ------------------------------------------------------------------
    fmt(value) {
        return Math.round(value || 0).toLocaleString("es-AR");
    }

    d1(value) {
        return (value || 0).toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    }

    dateLabel(iso) {
        if (!iso) {
            return "";
        }
        return new Date(iso + "T12:00:00").toLocaleDateString("es-AR", { weekday: "short", day: "2-digit", month: "2-digit" });
    }

    /** Llama al servidor; un error se muestra como aviso y devuelve null, sin el diálogo de
     * error de Odoo, que en el celular tapa toda la app. */
    async call(method, args = []) {
        this.state.busy = true;
        try {
            return await this.orm.call(CLOSE_MODEL, method, args);
        } catch (error) {
            const message = (error.data && error.data.message) || error.message || String(error);
            this.notification.add(message, { type: "danger" });
            return null;
        } finally {
            this.state.busy = false;
        }
    }

    // ------------------------------------------------------------------
    // Lista de OF pendientes
    // ------------------------------------------------------------------
    async loadList() {
        const data = await this.call("poultry_mobile_pending");
        this.state.orders = data ? data.orders : [];
        this.state.screen = "list";
        this.state.order = null;
    }

    orderStatus(order) {
        let dead = "aves muertas sin cargar";
        if (order.dead_count) {
            dead = `${this.fmt(order.dead_count)} aves muertas`;
        } else if (order.complete) {
            dead = "sin aves muertas";
        }
        return {
            dead,
            lines: order.line_count
                ? `${order.loaded_count} de ${order.line_count} consumos confirmados`
                : "la OF no tiene componentes",
        };
    }

    // ------------------------------------------------------------------
    // Una OF
    // ------------------------------------------------------------------
    async openOrder(closeId) {
        const order = await this.call("poultry_mobile_data", [[closeId]]);
        if (!order) {
            return this.loadList();
        }
        this.fillForm(order);
        this.state.screen = "order";
    }

    fillForm(order) {
        this.state.order = order;
        this.state.form = {
            dead: order.dead_count ? String(order.dead_count) : "",
            note: "",
            lines: order.lines.map((line) => ({
                id: line.id,
                product: line.product,
                uom: line.uom,
                planned: line.planned,
                type: line.type,
                isKg: line.is_kg,
                picked: line.picked,
                unit: "kg",
                qty: formatNum(line.quantity),
            })),
        };
    }

    /** Cantidad en la unidad del componente (las bolsas se convierten a kg). */
    lineValue(line) {
        const value = parseNum(line.qty);
        return line.isKg && line.unit === "bag" ? value * this.state.order.feed_bag_kg : value;
    }

    setLineUnit(line, unit) {
        if (unit === line.unit) {
            return;
        }
        this.syncFromInputs();
        const kg = this.lineValue(line);
        line.unit = unit;
        line.qty = kg ? formatNum(unit === "kg" ? kg : kg / this.state.order.feed_bag_kg) : "";
    }

    lineAlt(line) {
        const order = this.state.order;
        const value = this.lineValue(line);
        const parts = [`previsto ${this.d1(line.planned)} ${line.uom}`];
        if (value && line.isKg) {
            parts.push(line.unit === "kg"
                ? `= ${this.d1(value / order.feed_bag_kg)} bolsas de ${this.fmt(order.feed_bag_kg)} kg`
                : `= ${this.fmt(value)} kg`);
        }
        if (value && order.live_bird_count && line.type === "feed") {
            parts.push(`${this.fmt((value * 1000) / order.live_bird_count)} g por ave`);
        } else if (value && order.live_bird_count && line.type === "water") {
            parts.push(`${this.fmt((value * 1000) / order.live_bird_count)} ml por ave`);
        }
        return parts.join(" · ");
    }

    get deadValue() {
        return Math.round(parseNum(this.state.form.dead));
    }

    get deadPct() {
        const live = this.state.order.live_bird_count;
        const dead = this.deadValue;
        if (!live || !dead) {
            return "";
        }
        return this.d1((dead / live) * 100) + " % del galpón";
    }

    /** Más aves muertas que vivas: se avisa en la pantalla y no se deja guardar. */
    get deadTooMany() {
        const live = this.state.order.live_bird_count;
        return Boolean(live) && this.deadValue > live;
    }

    /** Lo que muestra cada campo es lo que se guarda: se relee la pantalla antes de usarlo,
     * por si algún evento de tipeo no llegó (visto en pre-prod en la grilla del parte). */
    syncFromInputs() {
        const root = this.formRef.el;
        if (!root) {
            return;
        }
        const dead = root.querySelector("[data-field='dead']");
        if (dead && dead.value !== this.state.form.dead) {
            this.state.form.dead = dead.value;
        }
        for (const line of this.state.form.lines) {
            const input = root.querySelector(`[data-field='line'][data-line='${line.id}']`);
            if (input && input.value !== line.qty) {
                line.qty = input.value;
            }
        }
    }

    /** Enter pasa al campo siguiente; en el último cierra el teclado. */
    onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const inputs = [...this.formRef.el.querySelectorAll("input[data-field]")];
        const next = inputs[inputs.indexOf(ev.target) + 1];
        if (next) {
            next.focus();
            next.select();
        } else {
            ev.target.blur();
        }
    }

    async saveOrder() {
        this.syncFromInputs();
        if (this.deadTooMany) {
            return;
        }
        const { id, coop, order_name } = this.state.order;
        const lines = this.state.form.lines.map((line) => ({ move_id: line.id, quantity: this.lineValue(line) }));
        const data = await this.call("poultry_mobile_save", [[id], this.deadValue, lines, this.state.form.note]);
        if (!data) {
            return;
        }
        this.notification.add(`OF ${order_name} de ${coop}: aves muertas y consumos guardados.`, { type: "success" });
        await this.loadList();
    }
}
