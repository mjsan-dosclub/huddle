package com.hello.cards.admin;
import android.content.Context;
import android.security.keystore.*;
import android.util.Base64;
import java.security.KeyStore;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import java.nio.charset.StandardCharsets;
/** App-private, origin-bound session persistence. Passwords are never stored. */
final class SessionStore {
 static javax.crypto.SecretKey key()throws Exception{KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);String alias="hello-native-session";if(!store.containsAlias(alias)){KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");generator.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());generator.generateKey();}return(javax.crypto.SecretKey)store.getKey(alias,null);}
 static void clear(Context c){c.getSharedPreferences("native-auth",0).edit().clear().apply();}
 static String read(Context c,String origin){try{String[] parts=c.getSharedPreferences("native-auth",0).getString("session","").split(":");if(parts.length!=2)return "";Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(parts[0],Base64.NO_WRAP)));cipher.updateAAD(origin.getBytes(StandardCharsets.UTF_8));return new String(cipher.doFinal(Base64.decode(parts[1],Base64.NO_WRAP)),StandardCharsets.UTF_8);}catch(Exception e){clear(c);return "";}}
 static void write(Context c,String origin,String cookie){try{if(cookie.equals("hello_session=")){clear(c);return;}Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());cipher.updateAAD(origin.getBytes(StandardCharsets.UTF_8));String data=Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)+":"+Base64.encodeToString(cipher.doFinal(cookie.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP);c.getSharedPreferences("native-auth",0).edit().putString("session",data).apply();}catch(Exception e){clear(c);/* Continue in memory; a restart requires sign-in again. */}}
}
