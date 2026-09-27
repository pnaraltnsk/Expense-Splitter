// All data access lives here. Replace these mocked functions with HTTP calls when the API exists.
const STORAGE_KEY = 'owesome.mock.v1';
const seed = {
  groups: [{ id:'g1', name:'Lisbon long weekend', currency:'EUR', simplify:true, ownerToken:'owner-demo-token', memberToken:'member-demo-token', members:[
    {id:'m1',name:'You'},{id:'m2',name:'Maya Chen'},{id:'m3',name:'Leo Martin'},{id:'m4',name:'Sam Rivera'}], expenses:[
      {id:'e1',description:'Dinner at Taberna',amount:128.4,category:'Food',date:'2026-09-24',payers:[{memberId:'m2',amount:128.4}],participants:['m1','m2','m3','m4'],splitType:'equal'},
      {id:'e2',description:'Airport transfer',amount:42,category:'Transport',date:'2026-09-24',payers:[{memberId:'m1',amount:42}],participants:['m1','m2','m3','m4'],splitType:'equal'},
      {id:'e3',description:'Apartment · first night',amount:240,category:'Accommodation',date:'2026-09-23',payers:[{memberId:'m3',amount:240}],participants:['m1','m2','m3','m4'],splitType:'equal'},
      {id:'e4',description:'Groceries & snacks',amount:36.8,category:'Food',date:'2026-09-23',payers:[{memberId:'m4',amount:36.8}],participants:['m1','m2','m3','m4'],splitType:'equal'}], settlements:[{id:'s1',from:'m1',to:'m2',amount:24,status:'pending',createdAt:'2026-09-25'}], recurring:[]
  }], role:'owner', activeGroupId:'g1', currentMemberId:'m1'
};
let state;
function load(){ if(state)return state; try{state=JSON.parse(localStorage.getItem(STORAGE_KEY))||clone(seed)}catch{state=clone(seed)} save(); return state; }
function save(){localStorage.setItem(STORAGE_KEY,JSON.stringify(state));}
const clone=(x)=>JSON.parse(JSON.stringify(x));
const wait=()=>new Promise(r=>setTimeout(r,120));
export const api={
 async getApp(){await wait();return clone(load())},
 async selectGroup(id){load().activeGroupId=id;save();return this.getApp()},
 async setRole(role){load().role=role;save();return this.getApp()},
 async setMember(id){load().currentMemberId=id;save();return this.getApp()},
 async createGroup({name,currency}){await wait();const s=load();const group={id:crypto.randomUUID(),name,currency,simplify:true,ownerToken:crypto.randomUUID(),memberToken:crypto.randomUUID(),members:[{id:crypto.randomUUID(),name:'You'}],expenses:[],settlements:[],recurring:[]};s.groups.unshift(group);s.activeGroupId=group.id;s.role='owner';s.currentMemberId=group.members[0].id;save();return this.getApp()},
 async addMember(name){await wait();const g=active();g.members.push({id:crypto.randomUUID(),name});save();return this.getApp()},
 async removeMember(id){await wait();const g=active();g.members=g.members.filter(m=>m.id!==id);g.expenses.forEach(e=>{e.participants=e.participants.filter(x=>x!==id);e.payers=e.payers.filter(p=>p.memberId!==id)});g.settlements=g.settlements.filter(x=>x.from!==id&&x.to!==id);save();return this.getApp()},
 async saveExpense(input){await wait();const g=active();const expense={...input,id:input.id||crypto.randomUUID()};const i=g.expenses.findIndex(x=>x.id===expense.id);if(i<0)g.expenses.unshift(expense);else g.expenses[i]=expense;save();return this.getApp()},
 async deleteExpense(id){await wait();const g=active();g.expenses=g.expenses.filter(e=>e.id!==id);save();return this.getApp()},
 async toggleSimplify(){await wait();const g=active();g.simplify=!g.simplify;save();return this.getApp()},
 async markPaid({to,amount}){await wait();const g=active();g.settlements.unshift({id:crypto.randomUUID(),from:load().currentMemberId,to,amount:Number(amount),status:'pending',createdAt:new Date().toISOString().slice(0,10)});save();return this.getApp()},
 async confirmSettlement(id){await wait();const x=active().settlements.find(s=>s.id===id);if(x)x.status='confirmed';save();return this.getApp()},
 async addRecurring(input){await wait();active().recurring.push({...input,id:crypto.randomUUID()});save();return this.getApp()},
 async deleteRecurring(id){await wait();const g=active();g.recurring=g.recurring.filter(x=>x.id!==id);save();return this.getApp()},
 async resetDemo(){state=clone(seed);save();return this.getApp()}
};
function active(){const s=load();return s.groups.find(g=>g.id===s.activeGroupId)}
