/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

/**
 * Custom widget for subscriber documents.
 * Renders attachments as a vertical list with full filenames and opens
 * files for preview in a new tab instead of triggering a download.
 */
export class SubscriberDocumentField extends Many2ManyBinaryField {
    static template = "odoo_subscription_manager.SubscriberDocumentField";

    /**
     * Override to use download=false so the browser renders a preview
     * (inline PDF viewer, image viewer, etc.) instead of forcing a download.
     */
    getUrl(id) {
        return `/web/content/${id}?download=false`;
    }
}

export const subscriberDocumentField = {
    ...many2ManyBinaryField,
    component: SubscriberDocumentField,
};

registry.category("fields").add("subscriber_document", subscriberDocumentField);
