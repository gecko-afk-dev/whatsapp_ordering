import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div>
            <h2 class="text-2xl font-bold text-slate-800 mb-6">Overview</h2>
            
            <div v-if="loading" class="animate-pulse flex space-x-4">
                <div class="flex-1 space-y-4 py-1">
                    <div class="h-4 bg-slate-200 rounded w-3/4"></div>
                    <div class="space-y-2">
                        <div class="h-4 bg-slate-200 rounded"></div>
                        <div class="h-4 bg-slate-200 rounded w-5/6"></div>
                    </div>
                </div>
            </div>

            <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <!-- Admin Stats -->
                <template v-if="user.role === 'admin'">
                    <StatCard title="Total Restaurants" :value="adminStats.total_restaurants" icon="R" color="blue" />
                    <StatCard title="Active Restaurants" :value="adminStats.active_restaurants" icon="A" color="green" />
                    <StatCard title="Orders Today" :value="adminStats.total_orders_today" icon="O" color="purple" />
                    <StatCard title="Revenue Today" :value="'$' + (adminStats.total_revenue_today || 0).toFixed(2)" icon="$" color="amber" />
                </template>
                
                <!-- Restaurant Owner Stats -->
                <template v-if="user.role === 'restaurant_owner'">
                    <StatCard title="Orders Today" :value="ownerStats.orders" icon="O" color="blue" />
                    <StatCard title="Revenue Today" :value="'$' + (ownerStats.revenue || 0).toFixed(2)" icon="$" color="green" />
                </template>
            </div>
        </div>
    `,
    props: ['user'],
    components: {
        StatCard: {
            props: ['title', 'value', 'icon', 'color'],
            template: `
                <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 flex items-center card-hover">
                    <div :class="colorClass" class="w-12 h-12 rounded-lg flex items-center justify-center text-white font-bold text-xl shadow-inner">
                        {{ icon }}
                    </div>
                    <div class="ml-4">
                        <h3 class="text-sm font-medium text-slate-500 uppercase tracking-wider">{{ title }}</h3>
                        <p class="text-2xl font-bold text-slate-800 mt-1">{{ value || 0 }}</p>
                    </div>
                </div>
            `,
            computed: {
                colorClass() {
                    const colors = {
                        blue: 'bg-blue-500',
                        green: 'bg-emerald-500',
                        purple: 'bg-purple-500',
                        amber: 'bg-amber-500'
                    };
                    return colors[this.color] || 'bg-slate-500';
                }
            }
        }
    },
    setup(props) {
        const loading = ref(true);
        const adminStats = ref({});
        const ownerStats = ref({ orders: 0, revenue: 0 });

        const loadStats = async () => {
            loading.value = true;
            try {
                if (props.user.role === 'admin') {
                    const res = await api.get('/admin/analytics/summary');
                    adminStats.value = res.data;
                } else if (props.user.role === 'restaurant_owner') {
                    const res = await api.get('/admin/restaurant/dashboard');
                    ownerStats.value = res.data.today_stats || { orders: 0, revenue: 0 };
                }
            } catch (err) {
                console.error("Failed to load stats", err);
            } finally {
                loading.value = false;
            }
        };

        onMounted(() => {
            loadStats();
        });

        return { loading, adminStats, ownerStats };
    }
}
