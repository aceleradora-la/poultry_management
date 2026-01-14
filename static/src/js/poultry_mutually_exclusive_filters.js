/** @odoo-module **/

import { registry } from "@web/core/registry";
import { SearchModel } from "@web/search/search_model";

/**
 * Extensión del SearchModel para hacer que los filtros "Sin Procesar" y "Procesada"
 * sean mutuamente excluyentes en la vista de producción.
 */
export const poultryMutuallyExclusiveFilters = {
    dependencies: ["search"],
    start(env, { search }) {
        const originalApplySearchQuery = search.applySearchQuery.bind(search);
        
        search.applySearchQuery = function(query) {
            // Solo aplicar la lógica si estamos en el modelo poultry.egg.collection
            if (this.config.resModel === 'poultry.egg.collection') {
                const activeFilters = query.filters || [];
                const hasNotDone = activeFilters.some(f => f.name === 'not_done');
                const hasDone = activeFilters.some(f => f.name === 'done');
                
                // Si ambos filtros están activos, remover "Sin Procesar" cuando se activa "Procesada"
                if (hasDone && hasNotDone) {
                    query.filters = activeFilters.filter(f => f.name !== 'not_done');
                }
            }
            
            return originalApplySearchQuery(query);
        };
    },
};

registry.category("services").add("poultry_mutually_exclusive_filters", poultryMutuallyExclusiveFilters);
