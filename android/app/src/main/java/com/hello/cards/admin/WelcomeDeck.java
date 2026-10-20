package com.hello.cards.admin;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.view.*;
import android.widget.*;

/** Full-screen native welcome scenes; no network claims or WebView rendering. */
final class WelcomeDeck extends FrameLayout {
    final MainActivity a;
    final int page;
    float startX,startY;
    final boolean loading;
    WelcomeDeck(MainActivity activity,int selected,boolean splash){
        super(activity);a=activity;page=selected;loading=splash;
        setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{0xfffffcf7,0xfffff1e9,0xfffffaf6}));
        if(splash){splash();return;}
        setClickable(true);setOnClickListener(v->advance());
        ScrollView scroll=new ScrollView(a);scroll.setFillViewport(true);scroll.setClipToPadding(false);
        LinearLayout body=new LinearLayout(a);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(a.dp(28),a.dp(24),a.dp(28),a.dp(100));scroll.addView(body,new ScrollView.LayoutParams(-1,-1));
        addView(scroll,new FrameLayout.LayoutParams(-1,-1));
        TextView kicker=label("h*  /  "+(page+1)+" OF 3",13,a.MUTED);kicker.setLetterSpacing(.12f);body.addView(kicker);
        if(page==0){
            spacer(body,48);headline(body,"Every hello.\nA new\npossibility.",46);
            paragraph(body,"Your digital business card. A better way to meet, share and stay connected.");
            Art art=new Art(a,0);body.addView(art,new LinearLayout.LayoutParams(-1,a.dp(270)));art.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        }else{
            Art art=new Art(a,page);art.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            LinearLayout.LayoutParams artSize=new LinearLayout.LayoutParams(-1,0,1);artSize.topMargin=a.dp(12);art.setMinimumHeight(a.dp(255));body.addView(art,artSize);
            headline(body,page==1?"Your card.\nEverywhere you go.":"Make connections.\nUse less.",36);
            paragraph(body,page==1?"Choose a company-approved look. Share by QR, link or an optional NFC card. Nobody needs an app to meet you.":"Update your details. Reuse your NFC card. Keep good introductions going without another print run.");
            if(page==2){TextView note=label("Illustration: 200 paper cards avoided ≈ 0.33 kg of paper. Not measured savings.",12,a.MUTED);body.addView(note);}
        }
        LinearLayout controls=new LinearLayout(a);controls.setGravity(Gravity.CENTER_VERTICAL);controls.setPadding(a.dp(20),a.dp(10),a.dp(20),a.dp(12));
        controls.setBackgroundColor(0xfafffaf6);FrameLayout.LayoutParams cp=new FrameLayout.LayoutParams(-1,a.dp(80),Gravity.BOTTOM);addView(controls,cp);
        TextView skip=label("Skip",15,a.INK);skip.setGravity(Gravity.CENTER);skip.setContentDescription("Skip introduction");skip.setOnClickListener(v->a.finishIntro());controls.addView(skip,new LinearLayout.LayoutParams(a.dp(60),a.dp(52)));
        LinearLayout dots=new LinearLayout(a);dots.setGravity(Gravity.CENTER);controls.addView(dots,new LinearLayout.LayoutParams(0,a.dp(52),1));
        for(int i=0;i<3;i++){final int n=i;TextView dot=label(i==page?"●":"○",18,a.GREEN);dot.setGravity(Gravity.CENTER);dot.setContentDescription("Introduction page "+(i+1)+(i==page?", current":""));dot.setOnClickListener(v->a.showIntro(n));dots.addView(dot,new LinearLayout.LayoutParams(a.dp(40),a.dp(48)));}
        TextView next=label("↗",30,Color.WHITE);next.setGravity(Gravity.CENTER);next.setBackground(a.shape(a.GREEN,40));next.setContentDescription(page==2?"Finish introduction":"Next introduction page");next.setOnClickListener(v->advance());controls.addView(next,new LinearLayout.LayoutParams(a.dp(56),a.dp(56)));
        if(ValueAnimator.areAnimatorsEnabled()){setAlpha(0f);animate().alpha(1).setDuration(220).start();}
    }
    void advance(){if(page==2)a.finishIntro();else a.showIntro(page+1);}
    @Override public boolean dispatchTouchEvent(android.view.MotionEvent e){
        if(loading)return super.dispatchTouchEvent(e);
        if(e.getActionMasked()==android.view.MotionEvent.ACTION_DOWN){startX=e.getX();startY=e.getY();}
        if(e.getActionMasked()==android.view.MotionEvent.ACTION_UP){float dx=e.getX()-startX,dy=e.getY()-startY;if(Math.abs(dx)>a.dp(48)&&Math.abs(dx)>Math.abs(dy)*1.3f){android.view.MotionEvent cancel=android.view.MotionEvent.obtain(e);cancel.setAction(android.view.MotionEvent.ACTION_CANCEL);super.dispatchTouchEvent(cancel);cancel.recycle();if(dx<0)advance();else if(page>0)a.showIntro(page-1);return true;}}
        return super.dispatchTouchEvent(e);
    }
    TextView label(String value,int size,int color){TextView v=new TextView(a);v.setText(value);v.setTextColor(color);v.setTextSize(size);v.setFontFeatureSettings("kern");return v;}
    void spacer(LinearLayout body,int height){body.addView(new View(a),new LinearLayout.LayoutParams(1,a.dp(height)));}
    void headline(LinearLayout body,String value,int size){TextView v=label(value,size,a.INK);v.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));v.setLineSpacing(a.dp(1),1);v.setLetterSpacing(-.035f);body.addView(v,new LinearLayout.LayoutParams(-1,-2));spacer(body,18);}
    void paragraph(LinearLayout body,String value){TextView p=label(value,16,a.MUTED);p.setLineSpacing(a.dp(4),1);body.addView(p,new LinearLayout.LayoutParams(-1,-2));spacer(body,12);}
    void splash(){
        addView(new Art(a,3),new FrameLayout.LayoutParams(-1,-1));
        LinearLayout body=new LinearLayout(a);body.setOrientation(1);body.setGravity(Gravity.CENTER_HORIZONTAL);body.setPadding(a.dp(30),a.dp(48),a.dp(30),a.dp(30));
        FrameLayout.LayoutParams bp=new FrameLayout.LayoutParams(-1,-2,Gravity.TOP);addView(body,bp);
        TextView logo=label("h*",45,a.GREEN);logo.setTypeface(null,Typeface.BOLD);body.addView(logo);
        TextView title=label("A small card.\nA lighter footprint.",28,a.INK);title.setGravity(Gravity.CENTER);title.setTypeface(null,Typeface.BOLD);body.addView(title);
        TextView estimate=label("200 paper cards ≈ 0.33 kg of paper",15,a.MUTED);estimate.setGravity(Gravity.CENTER);estimate.setPadding(0,a.dp(18),0,0);body.addView(estimate);
        TextView note=label("Illustrative annual scenario for one person.\nNot your measured activity. Assumes 85 × 55 mm, 350 gsm cards.",12,a.MUTED);note.setGravity(Gravity.CENTER);body.addView(note);
        LinearLayout status=new LinearLayout(a);status.setGravity(Gravity.CENTER);status.setOrientation(1);status.setPadding(a.dp(28),a.dp(20),a.dp(28),a.dp(26));FrameLayout.LayoutParams sp=new FrameLayout.LayoutParams(-1,-2,Gravity.BOTTOM);addView(status,sp);
        ProgressBar progress=new ProgressBar(a);progress.setIndeterminateTintList(android.content.res.ColorStateList.valueOf(a.GREEN));progress.setContentDescription("Loading workspace");status.addView(progress,new LinearLayout.LayoutParams(a.dp(28),a.dp(28)));
        TextView caption=label("Opening your workspace…",14,a.INK);caption.setPadding(0,a.dp(12),0,0);status.addView(caption);
    }
    static final class Art extends View {
        final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final int scene;float phase;ValueAnimator animator;
        Art(Context context,int kind){super(context);scene=kind;setMinimumHeight(((MainActivity)context).dp(220));}
        void run(){if(animator!=null||!ValueAnimator.areAnimatorsEnabled())return;animator=ValueAnimator.ofFloat(0,1);animator.setDuration(4200);animator.setRepeatCount(ValueAnimator.INFINITE);animator.setRepeatMode(ValueAnimator.REVERSE);animator.addUpdateListener(v->{phase=(float)v.getAnimatedValue();invalidate();});animator.start();}
        void stop(){if(animator!=null){animator.cancel();animator=null;}}
        @Override protected void onAttachedToWindow(){super.onAttachedToWindow();run();}
        @Override protected void onDetachedFromWindow(){stop();super.onDetachedFromWindow();}
        @Override protected void onWindowVisibilityChanged(int v){super.onWindowVisibilityChanged(v);if(v==VISIBLE)run();else stop();}
        void round(Canvas c,float x,float y,float w,float h,int color){p.setColor(color);c.drawRoundRect(x,y,x+w,y+h,22,22,p);}
        void card(Canvas c,float x,float y,float angle,int color,String name,String company){c.save();c.rotate(angle,x+108,y+65);round(c,x+2,y+7,216,130,0x10000000);round(c,x,y,216,130,color);p.setColor((color==0xff262020||color==0xffe61219)?0xfffffaf6:0xff272020);p.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));p.setTextSize(16);c.drawText(name,x+20,y+54,p);p.setTextSize(10);c.drawText(company,x+20,y+73,p);p.setTextSize(26);c.drawText("h*",x+172,y+33,p);p.setColor((color==0xff262020||color==0xffe61219)?0xfff3d6c6:0xffe61219);c.drawCircle(x+31,y+25,10,p);for(int i=0;i<3;i++)round(c,x+20,y+90+i*8,90-i*15,3,p.getColor());c.restore();}
        @Override protected void onDraw(Canvas original){super.onDraw(original);Canvas c=original;float width=getWidth(),height=getHeight();c.save();
            if(scene==3){
                p.setShader(new LinearGradient(0,height*.4f,width,height,new int[]{0xffffe3d3,0xfff8bbaa},null,Shader.TileMode.CLAMP));float wave=height*(.64f-.025f*phase);Path fill=new Path();fill.moveTo(0,wave);fill.cubicTo(width*.3f,wave-35*phase,width*.7f,wave+35*phase,width,wave);fill.lineTo(width,height);fill.lineTo(0,height);fill.close();c.drawPath(fill,p);p.setShader(null);
                c.translate(width/2,height*.62f);float scale=Math.min(width/390,height/780);c.scale(scale,scale);leaf(c,phase);c.restore();return;
            }
            c.translate(width/2,height/2);float scale=Math.min(width/334,height/260);c.scale(scale,scale);c.translate(-167,-130+phase*5);
            if(scene==0){p.setColor(0xffffddce);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(32);Path loop=new Path();loop.moveTo(360,50);loop.cubicTo(80,-60,100,140,320,170);loop.cubicTo(490,220,170,310,90,230);c.drawPath(loop,p);p.setStyle(Paint.Style.FILL);card(c,32,60,-12,0xffe61219,"Kavin Subramanian","MARINA WORKS · CHENNAI");}
            else if(scene==1){card(c,69,17,10,0xfff8d9ba,"Meera Nair","MALABAR STUDIO · KOCHI");card(c,33,66,-10,0xff262020,"Kavin Subramanian","MARINA WORKS · CHENNAI");card(c,68,130,5,0xfffffdf8,"Sravya Reddy","DECCAN COLLECTIVE");}
            else{p.setColor(0xffffe2d2);c.drawCircle(175,130,113,p);c.save();c.translate(175,162);leaf(c,phase);c.restore();p.setColor(0xffe61219);p.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));p.setTextSize(14);c.drawText("ONE CARD. MANY HELLOS.",74,258,p);}
            c.restore();
        }
        void leaf(Canvas c,float growth){p.setColor(0xffb43b35);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(5);Path stem=new Path();stem.moveTo(0,65);stem.cubicTo(-12,20,16,-30,0,-78-growth*6);c.drawPath(stem,p);p.setStyle(Paint.Style.FILL);p.setColor(0xffe61219);Path left=new Path();left.moveTo(0,6);left.cubicTo(-90,10,-87,-72,-58,-75);left.cubicTo(-18,-77,-8,-22,0,6);c.drawPath(left,p);p.setColor(0xffb43b35);Path right=new Path();right.moveTo(1,-26);right.cubicTo(88,-13,92,-92,63,-99);right.cubicTo(27,-99,13,-64,1,-26);c.drawPath(right,p);p.setColor(0xffb43b35);c.drawOval(-40,63,40,72,p);}
    }
}
