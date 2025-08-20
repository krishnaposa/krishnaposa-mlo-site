
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.querySelector('.menu-toggle');
  const menu = document.querySelector('.menu');
  if(btn){
    btn.addEventListener('click', () => menu.classList.toggle('show'));
  }
});
