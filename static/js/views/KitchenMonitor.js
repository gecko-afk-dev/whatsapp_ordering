import { ref, onMounted, onUnmounted, computed } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    name: 'KitchenMonitor',
    template: `
        <div class="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans select-none overflow-hidden relative">
            <!-- Sound Alert toggle & Fullscreen indicator -->
            <div :class="flashScreen ? 'opacity-100' : 'opacity-0 pointer-events-none'" class="absolute inset-0 bg-red-600/30 z-50 transition-opacity duration-300"></div>

            <!-- Top Header -->
            <header class="bg-slate-900 border-b border-slate-800 px-6 py-4 flex justify-between items-center z-10 shrink-0">
                <div class="flex items-center space-x-4">
                    <div class="h-4 w-4 rounded-full" :class="wsConnected ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'"></div>
                    <h1 class="text-xl font-black tracking-wider text-slate-200">KITCHEN MONITOR</h1>
                </div>

                <div class="flex items-center space-x-6">
                    <div class="text-sm text-slate-400 font-medium">
                        Total Tickets: <span class="text-lg font-bold text-white">{{ orders.length }}</span>
                    </div>
                    <button @click="toggleSound" class="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/50 hover:bg-slate-800 text-xs font-semibold text-slate-300 transition-colors flex items-center gap-1.5">
                        <span v-if="soundEnabled">🔊 Sound On</span>
                        <span v-else>🔇 Sound Off</span>
                    </button>
                    <button @click="$emit('logout')" class="px-3 py-1.5 rounded-lg bg-rose-950/40 hover:bg-rose-900/60 text-xs font-semibold text-rose-300 transition-all border border-rose-900/50">
                        Exit
                    </button>
                </div>
            </header>

            <!-- Main Ticket Grid -->
            <main class="flex-1 p-6 overflow-y-auto min-h-0">
                <div v-if="loading" class="h-full flex flex-col items-center justify-center space-y-4">
                    <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-r-2 border-blue-500"></div>
                    <span class="text-lg text-slate-400 font-medium tracking-wide">Syncing with kitchen queue...</span>
                </div>

                <div v-else-if="orders.length === 0" class="h-full flex flex-col items-center justify-center text-slate-500 py-20">
                    <div class="w-20 h-20 bg-slate-900/60 rounded-3xl flex items-center justify-center border border-slate-800 mb-6">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-10 w-10 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                    </div>
                    <h2 class="text-2xl font-black text-slate-400 tracking-wide">ALL CLEAR</h2>
                    <p class="text-sm text-slate-600 mt-2 font-medium">No pending orders in the kitchen. Enjoy the break!</p>
                </div>

                <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 items-start">
                    <div v-for="order in activeCookingOrders" :key="order.id" 
                         :class="ticketBorderClass(order)" 
                         class="bg-slate-900 rounded-2xl shadow-xl overflow-hidden flex flex-col border-2 transition-all duration-300">
                        
                        <!-- Ticket Header -->
                        <div class="px-5 py-3 border-b border-slate-800 flex justify-between items-center bg-slate-900/80">
                            <div>
                                <span class="text-xs font-black text-slate-500 uppercase tracking-widest block">ORDER</span>
                                <span class="text-2xl font-black text-white">#{{ order.id }}</span>
                            </div>
                            <div class="text-right">
                                <span class="text-xs font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-300 uppercase tracking-wider block mb-1">
                                    {{ order.fulfillment_method }}
                                </span>
                                <span class="text-xs font-semibold" :class="timeElapsedColor(order)">
                                    {{ getElapsedTime(order.created_at) }}
                                </span>
                            </div>
                        </div>

                        <!-- Ticket Items -->
                        <div class="p-5 flex-1 space-y-4">
                            <div v-for="item in order.items" :key="item.id" class="flex items-start space-x-3 text-lg leading-snug">
                                <span class="font-extrabold text-blue-400 bg-blue-950/50 px-2.5 py-0.5 rounded border border-blue-900/30 text-xl min-w-[2.2rem] text-center">
                                    {{ item.quantity }}
                                </span>
                                <div class="flex-1 min-w-0">
                                    <span class="font-bold text-slate-100 block truncate">{{ item.name_en || 'Item #' + item.menu_item_id }}</span>
                                    <span v-if="item.name_fr" class="text-xs font-medium text-slate-400 block truncate">{{ item.name_fr }}</span>
                                </div>
                            </div>
                        </div>

                        <!-- Ticket Footer (Status badge only) -->
                        <div class="px-5 py-3 bg-slate-950/40 border-t border-slate-800/60 flex justify-between items-center text-xs">
                            <span class="font-extrabold text-slate-400 uppercase tracking-wider">STATUS</span>
                            <span :class="statusBadgeClass(order.status)" class="font-black uppercase px-2.5 py-0.5 rounded tracking-wide text-xs">
                                {{ order.status }}
                            </span>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    `,
    props: ['user'],
    emits: ['logout'],
    setup(props) {
        const orders = ref([]);
        const loading = ref(true);
        const wsConnected = ref(false);
        const soundEnabled = ref(true);
        const flashScreen = ref(false);
        const now = ref(new Date());
        let ws = null;
        let timer = null;

        // Auto-refresh the ticket timers every minute
        onMounted(() => {
            timer = setInterval(() => {
                now.value = new Date();
            }, 30000);
        });

        onUnmounted(() => {
            if (timer) clearInterval(timer);
        });

        const toggleSound = () => {
            soundEnabled.value = !soundEnabled.value;
        };

        const playAlertSound = () => {
            if (!soundEnabled.value) return;
            try {
                const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                // Play double high-pitch beep
                const playBeepAt = (time) => {
                    const osc = audioCtx.createOscillator();
                    const gain = audioCtx.createGain();
                    osc.connect(gain);
                    gain.connect(audioCtx.destination);
                    osc.type = 'sine';
                    osc.frequency.value = 880;
                    gain.gain.setValueAtTime(0.15, time);
                    osc.start(time);
                    osc.stop(time + 0.12);
                };
                const t = audioCtx.currentTime;
                playBeepAt(t);
                playBeepAt(t + 0.2);
            } catch (e) {
                console.warn('Audio Context error', e);
            }
        };

        const triggerAlertEffect = () => {
            playAlertSound();
            flashScreen.value = true;
            setTimeout(() => {
                flashScreen.value = false;
            }, 800);
        };

        const loadOrders = async () => {
            if (!props.user || !props.user.restaurant_id) return;
            try {
                const res = await api.get('/dashboard/orders/' + props.user.restaurant_id);
                // Compare length to determine if new orders arrived
                const previousCount = orders.value.length;
                
                // Keep only cooking orders: received, accepted, preparing
                // Filters out terminal and ready states
                orders.value = res.data.filter(o => ['received', 'accepted', 'preparing'].includes(o.status));
                
                if (orders.value.length > previousCount && !loading.value) {
                    triggerAlertEffect();
                }
            } catch (err) {
                console.error(err);
            } finally {
                loading.value = false;
            }
        };

        const initWebSocket = () => {
            if (!props.user || !props.user.restaurant_id) return;
            const token = localStorage.getItem('token');
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/api/v1/dashboard/ws/${props.user.restaurant_id}?token=${token}`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => { wsConnected.value = true; };
            ws.onclose = () => {
                wsConnected.value = false;
                setTimeout(initWebSocket, 3000);
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.event === 'NEW_ORDER' || data.event === 'ORDER_STATUS_UPDATED') {
                    loadOrders();
                }
            };
        };

        const activeCookingOrders = computed(() => {
            // Sort by elapsed time (oldest first)
            return [...orders.value].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        });

        const getElapsedTime = (created_at) => {
            const diff = now.value - new Date(created_at);
            const mins = Math.floor(diff / 60000);
            if (mins < 1) return 'Just now';
            return `${mins}m ago`;
        };

        const timeElapsedColor = (order) => {
            const diff = now.value - new Date(order.created_at);
            const mins = Math.floor(diff / 60000);
            if (mins >= 15) return 'text-rose-500 font-bold';
            if (mins >= 10) return 'text-amber-500 font-semibold';
            return 'text-slate-400';
        };

        const ticketBorderClass = (order) => {
            const diff = now.value - new Date(order.created_at);
            const mins = Math.floor(diff / 60000);
            if (mins >= 15) return 'border-rose-600 animate-pulse';
            if (mins >= 10) return 'border-amber-600';
            if (order.status === 'received') return 'border-blue-600';
            return 'border-slate-800';
        };

        const statusBadgeClass = (status) => {
            if (status === 'received') return 'bg-blue-950 text-blue-400 border border-blue-900';
            if (status === 'accepted') return 'bg-amber-950 text-amber-400 border border-amber-900';
            if (status === 'preparing') return 'bg-purple-950 text-purple-400 border border-purple-900';
            return 'bg-slate-800 text-slate-400';
        };

        onMounted(() => {
            loadOrders();
            initWebSocket();
        });

        onUnmounted(() => {
            if (ws) ws.close();
        });

        return {
            orders,
            loading,
            wsConnected,
            soundEnabled,
            flashScreen,
            activeCookingOrders,
            toggleSound,
            getElapsedTime,
            timeElapsedColor,
            ticketBorderClass,
            statusBadgeClass
        };
    }
};
