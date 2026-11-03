const form=document.querySelector('#reset-form'),result=document.querySelector('#result'),token=new URLSearchParams(location.search).get('token');
if(!token){form.hidden=true;result.textContent='This reset link is incomplete. Ask your organization administrator for a new link.'}
form.addEventListener('submit',async event=>{
    event.preventDefault();const password=form.elements.namedItem('password').value;
    if(password!==form.elements.namedItem('confirm').value){result.textContent='The passwords do not match.';return}
    const button=form.querySelector('button');button.disabled=true;
    try{
        const response=await fetch('/api/password/recover',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,password})});
        const data=await response.json();if(!response.ok)throw Error(data.error||'Could not reset the password.');
        form.hidden=true;result.textContent='Password updated. You can sign in now.';history.replaceState({},'',location.pathname);
    }catch(error){result.textContent=error.message;button.disabled=false}
});
