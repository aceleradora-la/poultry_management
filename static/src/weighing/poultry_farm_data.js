import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const CLOSE_MODEL = "poultry.coop.close";
const EGG_MODEL = "poultry.egg.collection";

/**
 * Mortandad y consumos desde el celular. La OF de Huevo sin Clasificar que crea el Cierre de
 * Galpón se marca Hecha al otro día: hasta entonces el operador le carga las aves muertas y
 * la cantidad consumida de cada componente (alimento, agua, lo que tenga la lista). Los días
 * que todavía no tienen OF se cargan en el parte y el cierre los pasa a la OF al crearla.
 */
export class PoultryFarmData extends Component {
    static template = "poultry_management.PoultryFarmData";
    static props = { onHome: Function };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            screen: "list", // list | order | part
            orders: [],
            parts: [],
            order: null, // datos de la OF (poultry.coop.close.poultry_mobile_data)
            part: null, // datos del parte sin OF (poultry.egg.collection.poultry_mobile_data)
            form: { dead: "", note: "", lines: [] }, // lines: [{ id, product, uom, planned, type, isKg, unit, qty }]
            farm: { dead: "", feed: "", unit: "kg", notes: "" },
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

    qtyText(value) {
        return value ? String(Math.round(value * 100) / 100) : "";
    }

    dateLabel(iso) {
        if (!iso) {
            return "";
        }
        return new Date(iso + "T12:00:00").toLocaleDateString("es-AR", { weekday: "short", day: "2-digit", month: "2-digit" });
    }

    async call(model, method, args = [], kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call(model, method, args, kwargs);
        } catch (error) {
            const message = (error.data && error.data.message) || error.message || String(error);
            this.notification.add(message, { type: "danger" });
            throw error;
        } finally {
            this.state.busy = false;
        }
    }

    // ------------------------------------------------------------------
    // Lista
    // ------------------------------------------------------------------
    async loadList() {
        const data = await this.call(CLOSE_MODEL, "poultry_mobile_pending");
        this.state.orders = data.orders;
        this.state.parts = data.parts;
        this.state.screen = "list";
        this.state.order = null;
        this.state.part = null;
    }

    orderStatus(order) {
        const complete = order.dead_count > 0 && order.line_count > 0 && order.loaded_count === order.line_count;
        return {
            complete,
            dead: order.dead_count ? `${order.dead_count} aves muertas` : "sin aves muertas",
            lines: order.line_count
                ? `${order.loaded_count} de ${order.line_count} consumos confirmados`
                : "la OF no tiene componentes",
        };
    }

    // ------------------------------------------------------------------
    // OF de Huevo sin Clasificar
    // ------------------------------------------------------------------
    async openOrder(closeId) {
        this.state.order = await this.call(CLOSE_MODEL, "poultry_mobile_data", [[closeId]]);
        const order = this.state.order;
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
                qty: this.qtyText(line.quantity),
            })),
        };
        this.state.screen = "order";
    }

    /** Cantidad en la unidad del componente (las bolsas se convierten a kg). */
    lineValue(line) {
        const value = parseFloat(line.qty) || 0;
        return line.isKg && line.unit === "bag" ? value * this.state.order.feed_bag_kg : value;
    }

    setLineUnit(line, unit) {
        if (unit === line.unit) {
            return;
        }
        const kg = this.lineValue(line);
        line.unit = unit;
        line.qty = kg ? this.qtyText(unit === "kg" ? kg : kg / this.state.order.feed_bag_kg) : "";
    }

    lineAlt(line) {
        const order = this.state.order;
        const value = this.lineValue(line);
        const parts = [`previsto ${this.d1(line.planned)} ${line.uom}`];
        if (!line.picked) {
            parts.push("propuesto por la lista, sin confirmar");
        }
        if (!value) {
            return parts.join(" · ");
        }
        if (line.isKg) {
            parts.push(line.unit === "kg"
                ? `= ${this.d1(value / order.feed_bag_kg)} bolsas de ${this.fmt(order.feed_bag_kg)} kg`
                : `= ${this.fmt(value)} kg`);
        }
        if (order.live_bird_count && line.type === "feed") {
            parts.push(`${this.fmt((value * 1000) / order.live_bird_count)} g por ave`);
        } else if (order.live_bird_count && line.type === "water") {
            parts.push(`${this.fmt((value * 1000) / order.live_bird_count)} ml por ave`);
        }
        return parts.join(" · ");
    }

    get orderDeadPct() {
        const order = this.state.order;
        const dead = parseInt(this.state.form.dead) || 0;
        if (!order.live_bird_count || !dead) {
            return "";
        }
        return this.d1((dead / order.live_bird_count) * 100) + " % del galpón";
    }

    async saveOrder() {
        const { id, coop, order_name } = this.state.order;
        const lines = this.state.form.lines.map((line) => ({ move_id: line.id, quantity: this.lineValue(line) }));
        this.state.order = await this.call(CLOSE_MODEL, "poultry_mobile_save", [
            [id],
            parseInt(this.state.form.dead) || 0,
            lines,
            this.state.form.note,
        ]);
        this.notification.add(`OF ${order_name} de ${coop}: mortandad y consumos guardados.`, { type: "success" });
        await this.loadList();
    }

    // ------------------------------------------------------------------
    // Parte sin OF todavía
    // ------------------------------------------------------------------
    async openPart(partId) {
        this.state.part = await this.call(EGG_MODEL, "poultry_mobile_data", [[partId]]);
        const part = this.state.part;
        this.state.farm = {
            dead: part.dead_count ? String(part.dead_count) : "",
            feed: this.qtyText(part.feed_consumed_kg),
            unit: "kg",
            notes: part.farm_notes || "",
        };
        this.state.screen = "part";
    }

    get feedKg() {
        const value = parseFloat(this.state.farm.feed) || 0;
        return this.state.farm.unit === "kg" ? value : value * this.state.part.feed_bag_kg;
    }

    setUnit(unit) {
        const farm = this.state.farm;
        if (unit === farm.unit) {
            return;
        }
        const kg = this.feedKg;
        farm.unit = unit;
        farm.feed = kg ? this.qtyText(unit === "kg" ? kg : kg / this.state.part.feed_bag_kg) : "";
    }

    get feedAlt() {
        const part = this.state.part;
        const kg = this.feedKg;
        if (!kg) {
            return "";
        }
        const parts = [];
        parts.push(this.state.farm.unit === "kg"
            ? `= ${this.d1(kg / part.feed_bag_kg)} bolsas de ${this.fmt(part.feed_bag_kg)} kg`
            : `= ${this.fmt(kg)} kg`);
        if (part.live_bird_count) {
            parts.push(`${this.fmt((kg * 1000) / part.live_bird_count)} g por ave`);
        }
        return parts.join(" · ");
    }

    get partDeadPct() {
        const part = this.state.part;
        const dead = parseInt(this.state.farm.dead) || 0;
        if (!part.live_bird_count || !dead) {
            return "";
        }
        return this.d1((dead / part.live_bird_count) * 100) + " % del galpón";
    }

    async savePart() {
        const farm = this.state.farm;
        const { id, coop } = this.state.part;
        this.state.part = await this.call(EGG_MODEL, "poultry_mobile_save_farm", [
            [id],
            parseInt(farm.dead) || 0,
            this.feedKg,
            farm.notes,
        ]);
        this.notification.add(`Parte de ${coop}: mortandad y alimento guardados. Pasan a la OF cuando se haga el cierre.`, { type: "success" });
        await this.loadList();
    }
}
