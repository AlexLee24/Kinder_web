import re

with open('static/js/object_detail.js', 'r', encoding='utf-8') as f:
    text = f.read()

render_func = """function renderDetectData(results) {
    const detectBody = document.getElementById('detectBody');
    if (!detectBody) return;
    
    if (!results || results.length === 0) {
        detectBody.innerHTML = '<div style="display:flex; justify-content:center; align-items:center; height:100%; color:#888;">No matches found</div>';
        return;
    }

    let html = '<ul style="list-style:none; padding:0; margin:0;">';
    results.forEach(res => {
        let sep = parseFloat(res.separation_arcsec).toFixed(2);
        let catalog = res.catalog_name;
        let mdata = {};
        try {
            mdata = typeof res.match_data === 'string' ? JSON.parse(res.match_data) : res.match_data;
        } catch(e) {
            mdata = {};
        }
        
        let extraInfo = '';
        if ('z_lens' in mdata && mdata.z_lens !== null) extraInfo += ` | z_lens=${paimport re

with open('static/js/o}`
with op  e    text = f.read()

render_func = """function renderDetectData(reseF
render_func = """xed    const detectBody = document.getElementById('dete_s    if (!detectBody) return;
    
    if (!results || resultpe    
    if (!results || rese    (        detectBody.innerHTML = '<div style)         return;
    }

    let html = '<ul style="list-style:none; padding:0; margin:0;">';
    results.forEach(res => {
        let sep = parseFloat(r=$    }

    letat
   sou    results.forEach(res => {
        let sep = parseFloat(res.separnu        let sep = parseFloaxt        let catalog = res.catalog_name;
        let mdata = {}li        let mdata = {};
        try {
 !        try {
        `             se        } catch(e) {
            mdata = {};
        }
        
        let extraInfo !== null) extraI            mdata ={p        }
        
   to        }"                 if ('z_lens' iniorit
with open('static/js/o}`
with op  e    text = f.read()

render_func = """function renderDetx swith op  e    text = f.di
render_func = """function rmdarender_func = """xed    const detectBody = docu      
    if (!results || resultpe    
    if (!results || rese    (        detectBody.innerHTML = '<dpe   
     if (!results || rese    (   c    }

    let html = '<ul style="list-style:none; padding:0; margin:0;">';
    results  
     }    results.forEach(res => {
        let sep = parseFloat(r=$    }
 r        let sep = parseFloang
    letat
   sou    results.forEach      sou  iv        let sep = parseFloat(res.00        let mdata = {}li        let mdata = {};
        try {
 !        try {
        `             se     o}        try {
 !        try {
        `          !        trl>        `     te            mdata = {};
        }
        
te        }
        
   et        =        t.        
   to        }"                 if ('z_lens' iniorit
with ch   to  obwith open('static/js/o}`
with op  e    text = f.rea_mwith op  e    text = f.sp
render_func = """function r   render_func = """function rmdarender_func = """xed    const de      if (!results || resultpe    
    if (!results || rese    (        detectBody.iin    if (!results || rese    (  r(     if (!results || rese    (   c    }

    let html = '<ul style=}<
    let html = '<ul style="list-style       results  
     }    results.forEach(res => {
        let sep =        }   etect        let sep = parseFloat(r=$ or r        let sep = parseFloang
    >E    letat
   sou    results.fo     sou  }"        try {
 !        try {
        `             se     o}        try {
 !        try {
       , re.DOTALL)
text = pat !        trde        `   \n", !        try {
        `          !       js        `     ng     -8') as f:
    f.write(text)
