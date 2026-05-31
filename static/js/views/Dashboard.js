import { ref, computed } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import Overview from './Overview.js';
import RestaurantsAdmin from './RestaurantsAdmin.js';
import MenuManager from './MenuManager.js';
import DriversManager from './DriversManager.js';
import OrdersManager from './OrdersManager.js';
import StaffManager from './StaffManager.js';
import KitchenMonitor from './KitchenMonitor.js';
import AuditLog from './AuditLog.js';

export default {
    template: `
        <div class="min-h-screen bg-slate-50 flex flex-col">
            <!-- Header (Hidden for Kitchen Monitor) -->
            <header v-if="user.role !== 'kitchen_staff'" class="bg-white border-b border-slate-200 sticky top-0 z-30 shrink-0">
                <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div class="flex justify-between items-center h-16">
                        <div class="flex items-center">
                            <div class="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shadow-sm mr-3">
                                <span class="text-white font-bold text-lg leading-none">G</span>
                            </div>
                            <h1 class="text-xl font-bold text-slate-900 tracking-tight">GEQO Dashboard</h1>
                        </div>
                        <div class="flex items-center space-x-4">
                            <div class="hidden sm:flex flex-col items-end">
                                <span class="text-sm font-medium text-slate-900">{{ user.email }}</span>
                                <span class="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 mt-0.5 uppercase tracking-wider">{{ formatRole(user.role) }}</span>
                            </div>
                            <div class="w-px h-8 bg-slate-200 hidden sm:block"></div>
                            <button @click="$emit('logout')" class="text-sm font-semibold text-slate-500 hover:text-red-650 transition-colors px-2.5 py-1 rounded-lg hover:bg-slate-100">
                                Sign Out
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            <!-- Navigation (Hidden for Kitchen Monitor) -->
            <nav v-if="user.role !== 'kitchen_staff'" class="bg-white border-b border-slate-200 shadow-sm shrink-0">
                <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div class="flex space-x-1 py-3 overflow-x-auto hide-scrollbar">
                        <!-- Overview: Admin, Owner, Cashier -->
                        <button v-if="['admin', 'restaurant_owner', 'cashier'].includes(user.role)"
                                @click="currentView = 'overview'"
                                :class="currentView === 'overview' ? 'bg-slate-100 text-slate-955 font-bold shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'"
                                class="px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap">
                            Overview
                        </button>
                        
                        <!-- Active Orders: Owner, Cashier -->
                        <button v-if="['restaurant_owner', 'cashier'].includes(user.role)"
                                @click="currentView = 'orders'"
                                :class="currentView === 'orders' ? 'bg-slate-100 text-slate-955 font-bold shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'"
                                class="px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap relative">
                            Active Orders
                            <span class="absolute top-2 right-1.5 flex h-2 w-2">
                                <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                            </span>
                        </button>

                        <!-- Restaurants Admin: Admin only -->
                        <button v-slot v-if="user.role === 'admin'"
                                @click="currentView = 'restaurants'"
                                :class="currentView === 'restaurants' ? 'bg-slate-100 text-slate-955 font-bold shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'"
                                class="px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap">
                            Restaurants Admin
                        </button>

                        <!-- Menu Management: Admin, Owner, Cashier -->
                        <button v-if="['admin', 'restaurant_owner', 'cashier'].includes(user.role)"
                                @click="currentView = 'menu'"
                                :class="currentView === 'menu' ? 'bg-slate-100 text-slate-955 font-bold shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'"
                                class="px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap">
                            Menu Management
                        </button>
                        
                        <!-- Staff Management: Owner only -->
                        <button v-if="user.role === 'restaurant_owner'"
                                @click="currentView = 'staff'"
                                :class="currentView === 'staff' ? 'bg-slate-100 text-slate-955 font-bold shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'"
                                class="px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap">
                            Staff Management
                        </button>

                        <!-- Drivers: Admin, Owner, Cashier -->
                        <button v-if="['admin', 'restaurant_owner', 'cashier'].includes(user.role)"
                                @click="currentView = 'drivers'"
                                :class="currentView === 'drivers' ? 'bg-slate-100 text-slate-955 font-bold shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'"
                                class="px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap">
                            Drivers
                        </button>

                        <!-- Audit Logs: Admin, Owner -->
                        <button v-if="['admin', 'restaurant_owner'].includes(user.role)"
                                @click="currentView = 'audit-log'"
                                :class="currentView === 'audit-log' ? 'bg-slate-100 text-slate-955 font-bold shadow-sm' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'"
                                class="px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap">
                            Audit Logs
                        </button>
                    </div>
                </div>
            </nav>

            <!-- Content Area (Full screen class applied for kitchen staff monitor) -->
            <main :class="user.role === 'kitchen_staff' ? 'flex-1 flex flex-col h-screen min-h-0 bg-slate-950 p-0 m-0' : 'flex-1 max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8 w-full'">
                <component :is="currentComponent" :user="user" @logout="$emit('logout')"></component>
            </main>
        </div>
    `,
    components: {
        Overview,
        RestaurantsAdmin,
        MenuManager,
        DriversManager,
        OrdersManager,
        StaffManager,
        KitchenMonitor,
        AuditLog
    },
    props: {
        user: Object
    },
    emits: ['logout'],
    setup(props) {
        const defaultView = props.user.role === 'kitchen_staff' ? 'kitchen-monitor' : 'overview';
        const currentView = ref(defaultView);

        const currentComponent = computed(() => {
            const role = props.user.role;
            const view = currentView.value;

            if (role === 'kitchen_staff') return 'KitchenMonitor';

            if (view === 'overview' && ['admin', 'restaurant_owner', 'cashier'].includes(role)) return 'Overview';
            if (view === 'orders' && ['restaurant_owner', 'cashier'].includes(role)) return 'OrdersManager';
            if (view === 'restaurants' && role === 'admin') return 'RestaurantsAdmin';
            if (view === 'menu' && ['admin', 'restaurant_owner', 'cashier'].includes(role)) return 'MenuManager';
            if (view === 'staff' && role === 'restaurant_owner') return 'StaffManager';
            if (view === 'drivers' && ['admin', 'restaurant_owner', 'cashier'].includes(role)) return 'DriversManager';
            if (view === 'audit-log' && ['admin', 'restaurant_owner'].includes(role)) return 'AuditLog';
            
            return 'Overview';
        });

        const formatRole = (role) => {
            if (role === 'restaurant_owner') return 'Owner';
            if (role === 'kitchen_staff') return 'Kitchen Staff';
            return role;
        };

        return { currentView, currentComponent, formatRole };
    }
}
