import { ref, onMounted, onUnmounted, computed } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div>
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-slate-800 flex items-center">
                    Active Orders
                    <span v-if="wsConnected" class="ml-3 flex h-3 w-3 relative">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                    </span>
                    <span v-else class="ml-3 h-3 w-3 rounded-full bg-red-500"></span>
                </h2>
                <button @click="loadOrders" class="text-sm font-medium text-blue-600 hover:text-blue-800">
                    Refresh
                </button>
            </div>

            <div v-if="loading" class="text-center py-10 text-slate-500 animate-pulse">Loading orders...</div>

            <div v-else-if="orders.length === 0" class="bg-white rounded-xl shadow-sm border border-slate-200 p-10 text-center">
                <svg class="mx-auto h-12 w-12 text-slate-300 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path>
                </svg>
                <p class="text-slate-500 font-medium text-lg">No active orders right now.</p>
                <p class="text-slate-400 text-sm mt-1">New orders will appear here automatically.</p>
            </div>

            <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <div v-for="order in sortedOrders" :key="order.id" class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden flex flex-col card-hover">
                    <div class="px-5 py-4 border-b border-slate-100 flex justify-between items-center" :class="statusBgColor(order.status)">
                        <div>
                            <span class="font-bold text-slate-800">#{{ order.id }}</span>
                            <span class="text-xs font-medium ml-2 px-2 py-0.5 rounded-full bg-white text-slate-700 shadow-sm uppercase tracking-wide">{{ order.fulfillment_method }}</span>
                        </div>
                        <span class="text-sm font-bold text-slate-800">{{ order.total_price }} MAD</span>
                    </div>
                    <div class="p-5 flex-1">
                        <ul class="space-y-3 mb-4">
                            <li v-for="item in order.items" :key="item.id" class="text-sm flex justify-between">
                                <span class="text-slate-700">
                                    <span class="font-semibold">{{ item.quantity }}x</span> 
                                    {{ item.name_en || 'Item #' + item.menu_item_id }}
                                </span>
                                <span class="text-slate-500">{{ item.unit_price * item.quantity }} MAD</span>
                            </li>
                        </ul>
                        <div class="mt-4 pt-4 border-t border-slate-100">
                            <p class="text-xs text-slate-500 mb-2">Current Status: <strong class="uppercase text-slate-700">{{ order.status }}</strong></p>
                            
                            <!-- Actions based on status -->
                            <div class="flex space-x-2 mt-3">
                                <template v-if="order.status === 'received'">
                                    <button @click="updateStatus(order.id, 'accepted')" class="flex-1 btn-primary text-xs py-2 bg-blue-600 hover:bg-blue-700">Accept</button>
                                    <button @click="updateStatus(order.id, 'cancelled')" class="flex-1 btn-primary text-xs py-2 bg-red-600 hover:bg-red-700">Reject</button>
                                </template>
                                <template v-else-if="order.status === 'accepted'">
                                    <button @click="updateStatus(order.id, 'preparing')" class="flex-1 btn-primary text-xs py-2 bg-amber-500 hover:bg-amber-600">Start Preparing</button>
                                </template>
                                <template v-else-if="order.status === 'preparing'">
                                    <button v-if="order.fulfillment_method === 'pickup'" @click="updateStatus(order.id, 'ready')" class="flex-1 btn-primary text-xs py-2 bg-emerald-500 hover:bg-emerald-600">Mark Ready</button>
                                    <button v-else @click="updateStatus(order.id, 'ready')" class="flex-1 btn-primary text-xs py-2 bg-emerald-500 hover:bg-emerald-600">Ready for Driver</button>
                                </template>
                                <template v-else-if="order.status === 'ready'">
                                    <p class="text-xs text-slate-400 italic">Waiting for pickup/dispatch</p>
                                </template>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    props: ['user'],
    setup(props) {
        const orders = ref([]);
        const loading = ref(true);
        const wsConnected = ref(false);
        let ws = null;

        const loadOrders = async () => {
            if (!props.user || !props.user.restaurant_id) return;
            loading.value = true;
            try {
                const res = await api.get('/dashboard/orders/' + props.user.restaurant_id);
                orders.value = res.data;
            } catch (err) {
                console.error(err);
            } finally {
                loading.value = false;
            }
        };

        const updateStatus = async (id, newStatus) => {
            try {
                await api.post('/dashboard/orders/' + id + '/status', { new_status: newStatus });
                // Optimistically update
                const order = orders.value.find(o => o.id === id);
                if (order) order.status = newStatus;
                // If it goes to terminal state we might remove it or keep it until reload
                if (newStatus === 'cancelled' || newStatus === 'delivered') {
                    orders.value = orders.value.filter(o => o.id !== id);
                }
            } catch (err) {
                console.error(err);
                alert("Failed to update status");
            }
        };

        const initWebSocket = () => {
            if (!props.user || !props.user.restaurant_id) return;
            const token = localStorage.getItem('token');
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/api/v1/dashboard/ws/${props.user.restaurant_id}?token=${token}`;

            ws = new WebSocket(wsUrl);

            ws.onopen = () => { wsConnected.value = true; };
            ws.onclose = () => { wsConnected.value = false; setTimeout(initWebSocket, 3000); };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.event === 'NEW_ORDER' || data.event === 'ORDER_STATUS_UPDATED') {
                    loadOrders(); // Re-fetch the orders to get fresh data
                }
            };
        };

        const sortedOrders = computed(() => {
            // Sort by status priority then ID
            const statusWeights = { 'received': 1, 'accepted': 2, 'preparing': 3, 'ready': 4 };
            return [...orders.value].sort((a, b) => {
                const wa = statusWeights[a.status] || 99;
                const wb = statusWeights[b.status] || 99;
                if (wa !== wb) return wa - wb;
                return b.id - a.id;
            });
        });

        const statusBgColor = (status) => {
            const colors = {
                'received': 'bg-blue-50 border-b-blue-100',
                'accepted': 'bg-amber-50 border-b-amber-100',
                'preparing': 'bg-purple-50 border-b-purple-100',
                'ready': 'bg-emerald-50 border-b-emerald-100',
            };
            return colors[status] || 'bg-slate-50 border-b-slate-100';
        };

        onMounted(() => {
            loadOrders();
            initWebSocket();
        });

        onUnmounted(() => {
            if (ws) ws.close();
        });

        return { orders, loading, wsConnected, loadOrders, updateStatus, sortedOrders, statusBgColor };
    }
}