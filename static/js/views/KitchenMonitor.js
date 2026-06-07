/**
 * KitchenMonitor.js — Direction B redesign
 *
 * Layout B1 (Tablet/Desktop): 3-column Kanban — INCOMING | PREPARING | READY/DISPATCH
 * Layout B2 (Mobile):         single-column list with sticky tab filter (INC | PREP | RDY)
 *
 * Heuristic #1: Flashing saffron urgency border + beep for tickets >10 min in INCOMING
 * Heuristic #5: Confirmation bottom-sheet for critical status transitions
 * Mixed-script: item names wrapped in <div dir="auto"> with font-cairo
 * Driver dispatch: inline fleet selector in card header
 */
import {
    ref, computed, onMounted, onUnmounted, watch
} from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    name: 'KitchenMonitor',
    template: `
        <div class="min-h-screen bg-canvas text-slate-100 flex flex-col font-sans select-none overflow-hidden relative">

            <!-- Screen-flash alert overlay (new order or urgency trigger) -->
            <div :class="flashScreen ? 'opacity-100' : 'opacity-0 pointer-events-none'"
                 class="absolute inset-0 bg-saffron/10 z-50 transition-opacity duration-300 pointer-events-none">
            </div>

            <!-- ════════════════ HEADER ════════════════ -->
            <header class="bg-surface border-b border-white/[0.07] px-5 py-3.5 flex justify-between items-center z-10 shrink-0">
                <div class="flex items-center gap-3">
                    <div class="h-3.5 w-3.5 rounded-full transition-colors duration-500"
                         :class="wsConnected ? 'bg-emerald shadow-[0_0_8px_rgba(16,185,129,0.8)]' : 'bg-harissa'">
                    </div>
                    <span class="text-xs font-extrabold tracking-[0.2em] text-slate-400 uppercase">GEQO KDS</span>
                    <span class="text-sm text-slate-500">·</span>
                    <h1 class="text-base font-black text-slate-200 tracking-wide">KITCHEN MONITOR</h1>
                </div>

                <div class="flex items-center gap-4">
                    <div class="hidden sm:flex items-center gap-2 text-xs text-slate-500 font-semibold">
                        <span class="w-2 h-2 rounded-full bg-saffron inline-block"></span>
                        INCOMING: <span class="text-saffron font-black">{{ incomingOrders.length }}</span>
                        <span class="w-2 h-2 rounded-full bg-berry inline-block ml-2"></span>
                        PREP: <span class="text-berry font-black">{{ preparingOrders.length }}</span>
                        <span class="w-2 h-2 rounded-full bg-emerald inline-block ml-2"></span>
                        READY: <span class="text-emerald font-black">{{ readyOrders.length }}</span>
                    </div>

                    <button @click="toggleSound" id="kds-sound-toggle"
                            class="px-3 py-1.5 rounded-lg border border-white/10 bg-surface hover:bg-white/5 text-xs font-semibold text-slate-400 transition-all flex items-center gap-1.5">
                        <span v-if="soundEnabled">🔊</span>
                        <span v-else>🔇</span>
                    </button>

                    <button @click="$emit('logout')" id="kds-logout-btn"
                            class="px-3 py-1.5 rounded-lg bg-harissa/10 hover:bg-harissa/20 text-xs font-bold text-harissa transition-all border border-harissa/20">
                        Exit
                    </button>
                </div>
            </header>

            <!-- ════════════════ MOBILE TAB FILTER ════════════════ -->
            <div class="sm:hidden sticky top-0 z-20 bg-canvas border-b border-white/[0.07] flex">
                <button v-for="tab in mobileTabs" :key="tab.key"
                        @click="activeTab = tab.key"
                        :id="'kds-tab-' + tab.key"
                        class="flex-1 py-4 text-xs font-extrabold tracking-[0.12em] uppercase transition-all"
                        :class="activeTab === tab.key
                            ? 'text-' + tab.color + ' border-b-2 border-' + tab.color + ' bg-white/[0.04]'
                            : 'text-slate-600 border-b-2 border-transparent'">
                    {{ tab.label }} <span v-if="tab.count > 0" class="ml-1 opacity-80">({{ tab.count }})</span>
                </button>
            </div>

            <!-- ════════════════ MAIN AREA ════════════════ -->
            <main class="flex-1 overflow-hidden min-h-0">

                <!-- Loading state -->
                <div v-if="loading" class="h-full flex flex-col items-center justify-center gap-4 p-8">
                    <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-saffron"></div>
                    <span class="text-sm text-slate-500 font-semibold tracking-wide">Syncing kitchen queue…</span>
                </div>

                <!-- Empty state -->
                <div v-else-if="orders.length === 0"
                     class="h-full flex flex-col items-center justify-center gap-4 p-8 text-center">
                    <div class="w-20 h-20 rounded-3xl bg-surface flex items-center justify-center border border-white/[0.07] mb-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-9 w-9 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                    </div>
                    <h2 class="text-2xl font-black text-slate-500 tracking-widest">ALL CLEAR</h2>
                    <p class="text-sm text-slate-700 font-medium">No active kitchen tickets. Enjoy the break!</p>
                </div>

                <!-- ── TABLET/DESKTOP: 3-column Kanban ── -->
                <div v-else class="hidden sm:grid sm:grid-cols-3 gap-0 h-full divide-x divide-white/[0.05]">

                    <!-- INCOMING column -->
                    <div class="flex flex-col overflow-hidden">
                        <div class="kds-col-incoming px-5 py-3 flex items-center gap-2 bg-surface/40 shrink-0">
                            <span class="text-xs font-extrabold text-saffron tracking-[0.15em] uppercase">Incoming</span>
                            <span class="ml-auto bg-saffron/15 text-saffron text-xs font-black px-2 py-0.5 rounded-full">{{ incomingOrders.length }}</span>
                        </div>
                        <div class="flex-1 overflow-y-auto p-3 space-y-3">
                            <div v-if="incomingOrders.length === 0" class="py-10 text-center text-slate-700 text-xs font-semibold uppercase tracking-wider">Empty</div>
                            <div v-for="order in incomingOrders" :key="order.id"
                                 class="kds-ticket hover-glow-saffron cursor-default"
                                 :class="isUrgent(order) ? 'kds-ticket-urgent' : ''">
                                <div v-html="renderTicket(order, 'incoming')"></div>
                                <div class="px-4 pb-4">
                                    <button @click="promptTransition(order, 'preparing')"
                                            :id="'kds-accept-' + order.id"
                                            class="kds-action-btn w-full bg-saffron/10 hover:bg-saffron/20 text-saffron border border-saffron/30 rounded-lg text-sm font-bold mt-2">
                                        ✓ Accept & Start Preparing
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- PREPARING column -->
                    <div class="flex flex-col overflow-hidden">
                        <div class="kds-col-preparing px-5 py-3 flex items-center gap-2 bg-surface/40 shrink-0">
                            <span class="text-xs font-extrabold text-berry tracking-[0.15em] uppercase">Preparing</span>
                            <span class="ml-auto bg-berry/15 text-berry text-xs font-black px-2 py-0.5 rounded-full">{{ preparingOrders.length }}</span>
                        </div>
                        <div class="flex-1 overflow-y-auto p-3 space-y-3">
                            <div v-if="preparingOrders.length === 0" class="py-10 text-center text-slate-700 text-xs font-semibold uppercase tracking-wider">Empty</div>
                            <div v-for="order in preparingOrders" :key="order.id"
                                 class="kds-ticket hover-glow-berry cursor-default">
                                <div v-html="renderTicket(order, 'preparing')"></div>
                                <div class="px-4 pb-4">
                                    <button @click="promptTransition(order, 'ready')"
                                            :id="'kds-ready-' + order.id"
                                            class="kds-action-btn w-full bg-berry/10 hover:bg-berry/20 text-berry border border-berry/30 rounded-lg text-sm font-bold mt-2">
                                        ✓ Mark Ready
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- READY/DISPATCH column -->
                    <div class="flex flex-col overflow-hidden">
                        <div class="kds-col-ready px-5 py-3 flex items-center gap-2 bg-surface/40 shrink-0">
                            <span class="text-xs font-extrabold text-emerald tracking-[0.15em] uppercase">Ready / Dispatch</span>
                            <span class="ml-auto bg-emerald/15 text-emerald text-xs font-black px-2 py-0.5 rounded-full">{{ readyOrders.length }}</span>
                        </div>
                        <div class="flex-1 overflow-y-auto p-3 space-y-3">
                            <div v-if="readyOrders.length === 0" class="py-10 text-center text-slate-700 text-xs font-semibold uppercase tracking-wider">Empty</div>
                            <div v-for="order in readyOrders" :key="order.id"
                                 class="kds-ticket hover-glow-emerald cursor-default">
                                <div v-html="renderTicket(order, 'ready')"></div>
                                <!-- Driver dispatch selector -->
                                <div v-if="order.fulfillment_method === 'delivery'" class="px-4 pb-4">
                                    <select :id="'kds-driver-' + order.id"
                                            v-model="selectedDrivers[order.id]"
                                            class="w-full bg-canvas border border-white/10 text-slate-300 rounded-lg px-3 py-2 text-xs font-semibold mb-2 focus:border-emerald outline-none">
                                        <option value="">— Assign Driver —</option>
                                        <option v-for="d in drivers" :key="d.id" :value="d.id">{{ d.name }}</option>
                                    </select>
                                    <button @click="promptTransition(order, 'dispatched')"
                                            :disabled="!selectedDrivers[order.id]"
                                            :id="'kds-dispatch-' + order.id"
                                            class="kds-action-btn w-full bg-emerald/10 hover:bg-emerald/20 text-emerald border border-emerald/30 rounded-lg text-sm font-bold disabled:opacity-40 disabled:cursor-not-allowed">
                                        🚚 Dispatch Driver
                                    </button>
                                </div>
                                <div v-else class="px-4 pb-4">
                                    <button @click="promptTransition(order, 'delivered')"
                                            :id="'kds-pickup-done-' + order.id"
                                            class="kds-action-btn w-full bg-emerald/10 hover:bg-emerald/20 text-emerald border border-emerald/30 rounded-lg text-sm font-bold">
                                        ✓ Picked Up
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- ── MOBILE: single-column filtered list ── -->
                <div v-if="!loading && orders.length > 0" class="sm:hidden h-full overflow-y-auto p-3 space-y-3">
                    <template v-for="order in mobileVisibleOrders" :key="order.id">
                        <div class="kds-ticket" :class="isUrgent(order) ? 'kds-ticket-urgent' : ''">
                            <div v-html="renderTicket(order, mobileColFor(order.status))"></div>
                            <div class="px-4 pb-4 space-y-2">
                                <button v-if="order.status === 'received'"
                                        @click="promptTransition(order, 'preparing')"
                                        class="kds-action-btn w-full bg-saffron/10 text-saffron border border-saffron/30 rounded-lg text-sm font-bold">
                                    ✓ Accept
                                </button>
                                <button v-if="order.status === 'accepted' || order.status === 'preparing'"
                                        @click="promptTransition(order, 'ready')"
                                        class="kds-action-btn w-full bg-berry/10 text-berry border border-berry/30 rounded-lg text-sm font-bold">
                                    ✓ Ready
                                </button>
                            </div>
                        </div>
                    </template>
                    <div v-if="mobileVisibleOrders.length === 0" class="py-12 text-center text-slate-700 text-xs uppercase font-bold tracking-widest">No tickets here</div>
                </div>
            </main>

            <!-- ════════════════ CONFIRMATION BOTTOM SHEET ════════════════ -->
            <!-- Heuristic #5: Accidental tap prevention for critical transitions -->
            <template v-if="pendingTransition">
                <div class="bottom-sheet-backdrop" @click="pendingTransition = null"></div>
                <div class="bottom-sheet">
                    <div class="w-10 h-1 bg-slate-700 rounded-full mx-auto mb-5"></div>
                    <h3 class="text-lg font-black text-slate-100 mb-1">Confirm Action</h3>
                    <p class="text-sm text-slate-400 mb-6">
                        Move <span class="text-saffron font-bold">Order #{{ pendingTransition.order.id }}</span>
                        to <span class="font-bold" :class="transitionColor">{{ pendingTransitionLabel }}</span>?
                    </p>
                    <div class="flex gap-3">
                        <button @click="pendingTransition = null" id="kds-confirm-cancel"
                                class="btn btn-ghost flex-1 text-sm">Cancel</button>
                        <button @click="executeTransition" id="kds-confirm-ok"
                                class="btn btn-saffron flex-1 text-sm">Confirm</button>
                    </div>
                </div>
            </template>
        </div>
    `,
    props: ['user'],
    emits: ['logout'],

    setup(props) {
        const orders        = ref([]);
        const drivers       = ref([]);
        const loading       = ref(true);
        const wsConnected   = ref(false);
        const soundEnabled  = ref(true);
        const flashScreen   = ref(false);
        const now           = ref(new Date());
        const activeTab     = ref('incoming');
        const selectedDrivers = ref({});
        const pendingTransition = ref(null);

        let ws    = null;
        let timer = null;

        // ── Computed columns ───────────────────────────────────────────────
        const incomingOrders = computed(() =>
            [...orders.value.filter(o => ['received', 'accepted'].includes(o.status))]
                .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
        );
        const preparingOrders = computed(() =>
            [...orders.value.filter(o => o.status === 'preparing')]
                .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
        );
        const readyOrders = computed(() =>
            [...orders.value.filter(o => ['ready', 'dispatched'].includes(o.status))]
                .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
        );

        const mobileTabs = computed(() => [
            { key: 'incoming',  label: 'INC',  color: 'saffron', count: incomingOrders.value.length },
            { key: 'preparing', label: 'PREP', color: 'berry',   count: preparingOrders.value.length },
            { key: 'ready',     label: 'RDY',  color: 'emerald', count: readyOrders.value.length },
        ]);

        const mobileVisibleOrders = computed(() => {
            if (activeTab.value === 'incoming')  return incomingOrders.value;
            if (activeTab.value === 'preparing') return preparingOrders.value;
            return readyOrders.value;
        });

        const mobileColFor = (status) => {
            if (['received','accepted'].includes(status)) return 'incoming';
            if (status === 'preparing') return 'preparing';
            return 'ready';
        };

        const isUrgent = (order) => {
            const mins = Math.floor((now.value - new Date(order.created_at)) / 60000);
            return mins >= 10 && ['received','accepted'].includes(order.status);
        };

        const getElapsedTime = (created_at) => {
            const mins = Math.floor((now.value - new Date(created_at)) / 60000);
            if (mins < 1) return 'Just now';
            return `${mins}m ago`;
        };

        // ── Render ticket HTML (shared between desktop & mobile) ────────────
        const renderTicket = (order, col) => {
            const headerAccentClass = col === 'incoming'  ? 'border-saffron/40' :
                                      col === 'preparing' ? 'border-berry/40'   : 'border-emerald/40';
            const timeClass = isUrgent(order) ? 'text-saffron font-black animate-pulse' : 'text-slate-500';
            const elapsed = getElapsedTime(order.created_at);
            const fulfillBadge = order.fulfillment_method === 'delivery'
                ? '<span class="badge badge-saffron">🛵 Delivery</span>'
                : '<span class="badge badge-slate">🥡 Pickup</span>';

            // Location link if coordinates present
            const locationHtml = (order.latitude && order.longitude)
                ? `<a href="https://maps.google.com/?q=${order.latitude},${order.longitude}"
                       target="_blank" rel="noopener"
                       class="inline-flex items-center gap-1 text-xs text-saffron underline font-semibold mt-1">
                       📍 Maps / Waze
                   </a>`
                : '';

            const itemsHtml = (order.items || []).map(item => {
                const modsHtml = (item.modifiers || []).map(m =>
                    `<span class="kds-modifier-chip">${m.name_en || m.name_fr || ''}</span>`
                ).join(' ');
                const exclusionsHtml = (item.exclusions || []).map(e =>
                    `<span class="kds-modifier-chip">SANS ${e.toUpperCase()}</span>`
                ).join(' ');
                return `
                    <div class="flex items-start gap-2.5 py-1.5">
                        <span class="shrink-0 min-w-[2rem] text-center font-extrabold text-lg text-blue-400
                                     bg-blue-950/50 px-2 py-0.5 rounded border border-blue-900/30">
                            ${item.quantity}×
                        </span>
                        <div class="flex-1 min-w-0">
                            <div dir="auto" class="font-bold text-slate-100 text-sm leading-snug font-cairo">
                                ${item.name_en || item.name_fr || 'Item #' + item.menu_item_id}
                            </div>
                            ${item.name_fr && item.name_fr !== item.name_en
                                ? `<div class="text-xs text-slate-500 mt-0.5">${item.name_fr}</div>` : ''}
                            <div class="flex flex-wrap gap-1 mt-1.5">${modsHtml}${exclusionsHtml}</div>
                        </div>
                    </div>`;
            }).join('');

            return `
                <div class="px-4 pt-4 pb-3 border-b ${headerAccentClass} border-b border-white/[0.06] flex justify-between items-start">
                    <div>
                        <span class="text-[10px] font-black text-slate-600 uppercase tracking-widest block">Order</span>
                        <span class="text-2xl font-black text-white">#${order.id}</span>
                    </div>
                    <div class="text-right flex flex-col items-end gap-1.5">
                        ${fulfillBadge}
                        <span class="text-xs font-bold ${timeClass}">${elapsed}</span>
                        ${locationHtml}
                    </div>
                </div>
                <div class="px-4 py-3 space-y-1">${itemsHtml}</div>
            `;
        };

        // ── Pending transition (confirmation sheet) ────────────────────────
        const pendingTransitionLabel = computed(() => {
            if (!pendingTransition.value) return '';
            const map = { preparing: 'Preparing', ready: 'Ready', dispatched: 'Dispatched', delivered: 'Delivered' };
            return map[pendingTransition.value.to] || pendingTransition.value.to;
        });

        const transitionColor = computed(() => {
            if (!pendingTransition.value) return '';
            const map = { preparing: 'text-berry', ready: 'text-emerald', dispatched: 'text-emerald', delivered: 'text-emerald' };
            return map[pendingTransition.value.to] || 'text-saffron';
        });

        const promptTransition = (order, to) => {
            pendingTransition.value = { order, to };
        };

        const executeTransition = async () => {
            if (!pendingTransition.value) return;
            const { order, to } = pendingTransition.value;
            pendingTransition.value = null;
            try {
                await api.patch(`/dashboard/orders/${order.id}/status`, { status: to });
                await loadOrders();
            } catch (err) {
                console.error('[KDS] status update failed', err);
            }
        };

        // ── Data loading ────────────────────────────────────────────────────
        const loadOrders = async () => {
            if (!props.user?.restaurant_id) return;
            try {
                const res = await api.get('/dashboard/orders/' + props.user.restaurant_id);
                const previousCount = orders.value.filter(o => ['received','accepted'].includes(o.status)).length;
                orders.value = res.data.filter(o =>
                    ['received','accepted','preparing','ready','dispatched'].includes(o.status)
                );
                const newCount = orders.value.filter(o => ['received','accepted'].includes(o.status)).length;
                if (newCount > previousCount && !loading.value) triggerAlertEffect();
            } catch (err) {
                console.error('[KDS] loadOrders error', err);
            } finally {
                loading.value = false;
            }
        };

        const loadDrivers = async () => {
            if (!props.user?.restaurant_id) return;
            try {
                const res = await api.get('/drivers');
                drivers.value = res.data || [];
            } catch (err) {
                // Non-fatal: driver list is optional
                console.warn('[KDS] drivers load skipped', err);
            }
        };

        // ── WebSocket ───────────────────────────────────────────────────────
        const initWebSocket = () => {
            if (!props.user?.restaurant_id) return;
            const token    = localStorage.getItem('token');
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl    = `${protocol}//${window.location.host}/api/v1/dashboard/ws/${props.user.restaurant_id}?token=${token}`;

            ws = new WebSocket(wsUrl);
            ws.onopen    = () => { wsConnected.value = true; };
            ws.onclose   = () => { wsConnected.value = false; setTimeout(initWebSocket, 3000); };
            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (['NEW_ORDER','ORDER_STATUS_UPDATED'].includes(data.event)) loadOrders();
                } catch { /* ignore malformed messages */ }
            };
        };

        // ── Sound & Flash ───────────────────────────────────────────────────
        const toggleSound = () => { soundEnabled.value = !soundEnabled.value; };

        const playAlertSound = () => {
            if (!soundEnabled.value) return;
            try {
                const ctx  = new (window.AudioContext || window.webkitAudioContext)();
                const beep = (t) => {
                    const osc  = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.type = 'sine';
                    osc.frequency.value = 880;
                    gain.gain.setValueAtTime(0.15, t);
                    osc.start(t);
                    osc.stop(t + 0.12);
                };
                beep(ctx.currentTime);
                beep(ctx.currentTime + 0.22);
            } catch (e) {
                console.warn('[KDS] AudioContext error', e);
            }
        };

        const triggerAlertEffect = () => {
            playAlertSound();
            flashScreen.value = true;
            setTimeout(() => { flashScreen.value = false; }, 800);
        };

        // ── Lifecycle ───────────────────────────────────────────────────────
        onMounted(() => {
            loadOrders();
            loadDrivers();
            initWebSocket();
            // Tick the clock every 30s for elapsed-time display
            timer = setInterval(() => { now.value = new Date(); }, 30000);
        });

        onUnmounted(() => {
            if (ws)    ws.close();
            if (timer) clearInterval(timer);
        });

        return {
            orders, drivers, loading, wsConnected, soundEnabled, flashScreen,
            activeTab, selectedDrivers, pendingTransition,
            incomingOrders, preparingOrders, readyOrders,
            mobileTabs, mobileVisibleOrders, mobileColFor,
            isUrgent, renderTicket,
            pendingTransitionLabel, transitionColor,
            promptTransition, executeTransition, toggleSound,
        };
    }
};
