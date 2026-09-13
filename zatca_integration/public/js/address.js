frappe.ui.form.on("Address", {
	setup(frm) {
		// Keep last auto-filled values so we can refresh Arabic when English changes
		frm._zatca_arabic_autofilled = frm._zatca_arabic_autofilled || {};
	},

	refresh(frm) {
		toggle_saudi_address_requirements(frm);
		prefill_tax_category_from_party(frm);
		frm.add_custom_button(__("Translate Arabic Fields"), () => {
			translate_all_arabic_fields(frm, true);
		});
	},

	country(frm) {
		toggle_saudi_address_requirements(frm);
		autofill_arabic(frm, "country", "custom_country_in_arabic");
	},

	tax_category(frm) {
		toggle_saudi_address_requirements(frm);
	},

	address_line1(frm) {
		autofill_arabic(frm, "address_line1", "custom_street_in_arabic");
	},

	city(frm) {
		autofill_arabic(frm, "city", "custom_district_in_arabic");
	},

	county(frm) {
		autofill_arabic(frm, "county", "custom_city_in_arabic");
	},

	links_add(frm) {
		prefill_tax_category_from_party(frm);
	},
});

frappe.ui.form.on("Dynamic Link", {
	link_name(frm) {
		prefill_tax_category_from_party(frm);
	},
	link_doctype(frm) {
		prefill_tax_category_from_party(frm);
	},
});

function toggle_saudi_address_requirements(frm) {
	const is_sa = frm.doc.country === "Saudi Arabia";
	const is_export = frm.doc.tax_category === "Export / Non-Resident";
	const required = is_sa && !is_export;

	[
		"address_line1",
		"address_line2",
		"custom_additional_no",
		"city",
		"county",
		"pincode",
	].forEach((field) => {
		if (frm.fields_dict[field]) {
			frm.toggle_reqd(field, required);
		}
	});

	if (frm.fields_dict.custom_national_address) {
		frm.toggle_reqd("custom_national_address", false);
	}
}

function translate_all_arabic_fields(frm, force) {
	const pairs = [
		["address_line1", "custom_street_in_arabic"],
		["city", "custom_district_in_arabic"],
		["county", "custom_city_in_arabic"],
		["country", "custom_country_in_arabic"],
	];
	pairs.forEach(([source, target]) => autofill_arabic(frm, source, target, force));
}

function autofill_arabic(frm, source_field, target_field, force = false) {
	if (!frm.fields_dict[target_field]) {
		return;
	}

	const english = (frm.doc[source_field] || "").trim();
	if (!english) {
		return;
	}

	const arabic = (frm.doc[target_field] || "").trim();
	const previously_autofilled = (frm._zatca_arabic_autofilled || {})[target_field];

	// Do not overwrite a manual Arabic value unless user forced translate
	// or the current Arabic value was from our previous autofill for an older English value
	if (arabic && !force && arabic !== previously_autofilled) {
		return;
	}

	frappe.call({
		method: "zatca_integration.overrides.address.translate_text_to_arabic",
		args: { text: english, field: source_field },
		freeze: false,
		callback(r) {
			const translated = (r.message || "").trim();
			if (!translated) {
				frappe.show_alert({
					message: __("Could not translate {0} to Arabic. You can enter it manually.", [
						__(frm.fields_dict[source_field].df.label || source_field),
					]),
					indicator: "orange",
				});
				return;
			}
			// Skip if user typed Arabic meanwhile
			const current = (frm.doc[target_field] || "").trim();
			if (current && !force && current !== previously_autofilled) {
				return;
			}
			frm.set_value(target_field, translated);
			frm._zatca_arabic_autofilled[target_field] = translated;
		},
		error() {
			frappe.show_alert({
				message: __("Arabic translation request failed."),
				indicator: "red",
			});
		},
	});
}

function prefill_tax_category_from_party(frm) {
	if (frm.doc.tax_category || !frm.doc.links || !frm.doc.links.length) {
		return;
	}

	const link = (frm.doc.links || []).find(
		(row) => ["Customer", "Supplier"].includes(row.link_doctype) && row.link_name
	);
	if (!link) {
		return;
	}

	frappe.db.get_value(link.link_doctype, link.link_name, "tax_category").then((r) => {
		const tax_category = r && r.message && r.message.tax_category;
		if (tax_category && !frm.doc.tax_category) {
			frm.set_value("tax_category", tax_category);
		}
	});
}
