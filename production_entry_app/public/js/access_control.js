(function () {
	const ENDPOINT = "production_entry_app.production_entry_app.api.get_access_control_state";
	const DEFAULT_STATE = { enabled: false };
	let _state = null;
	let _statePromise = null;

	function _normalizeState(value) {
		return { enabled: Boolean(value && value.enabled) };
	}

	function _fetchState() {
		if (typeof frappe === "undefined" || typeof frappe.call !== "function") {
			_state = DEFAULT_STATE;
			return Promise.resolve(_state);
		}

		return new Promise((resolve) => {
			frappe.call({
				method: ENDPOINT,
				callback(r) {
					_state = _normalizeState(r?.message);
					resolve(_state);
				},
				error(error) {
					console.warn("Production Entry App access-control state fetch failed.", error);
					_state = DEFAULT_STATE;
					resolve(_state);
				},
			});
		});
	}

	function get_access_control_state() {
		if (!_statePromise) {
			_statePromise = _fetchState();
		}
		return _statePromise;
	}

	function get_cached_access_control_state() {
		return _state;
	}

	function is_app_enabled() {
		return Boolean(_state && _state.enabled);
	}

	const api = {
		get_access_control_state,
		get_cached_access_control_state,
		is_app_enabled,
		when_ready: get_access_control_state,
	};

	if (typeof window !== "undefined") {
		const PEA = (window.production_entry_app = window.production_entry_app || {});
		PEA.access_control = api;
	}

	if (typeof module !== "undefined" && module.exports) {
		module.exports = api;
	}

	void get_access_control_state();
})();
