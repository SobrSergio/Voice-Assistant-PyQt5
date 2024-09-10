import os
import sys
import shutil
import wave
import tempfile

import pyaudio
import sounddevice as sd
from pydub import AudioSegment
import speech_recognition as sr

from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QDialog, QComboBox, 
                             QLabel, QVBoxLayout, QHBoxLayout, QDesktopWidget, QAction, 
                             QFileDialog, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QIcon


from PyQt5.QtWidgets import QMessageBox




# Для записи в отдельном потоке.
class AudioPlayer(QThread):
    def __init__(self, file_path, device_index=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.device_index = device_index
        self.paused = False
        self.stopped = False
        
        try:
            self.wf = wave.open(self.file_path, 'rb')
        except wave.Error as e:
            self.show_error_message("Error opening file", str(e))
        except Exception as e:
            self.show_error_message("Unexpected error", str(e))

    def run(self):
        try:
            wf = wave.open(self.file_path, 'rb')
        except wave.Error as e:
            self.show_error_message("Error opening file", str(e))
            return
        except Exception as e:
            self.show_error_message("Unexpected error", str(e))
            return

        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                            channels=wf.getnchannels(),
                            rate=wf.getframerate(),
                            output=True, 
                            output_device_index=self.device_index)
        except Exception as e:
            self.show_error_message("Error initializing audio stream", str(e))
            return

        try:
            data = wf.readframes(1024)
            while data and not self.stopped: 
                while self.paused:
                    pass
                stream.write(data)
                data = wf.readframes(1024)
        except Exception as e:
            self.show_error_message("Error during playback", str(e))
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
    
    def stop(self): 
        self.stopped = True

    def show_error_message(self, title, message):
        QMessageBox.warning(None, title, message)



# Для записи аудио в отдельном потоке.
class AudioRecorder(QThread):
    finished_recording = pyqtSignal(str)
    
    def __init__(self, file_path, device_index=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.device_index = device_index
        self.recording = False

    def run(self):
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 44100

        try:
            audio = pyaudio.PyAudio()
            stream = audio.open(format=FORMAT,
                                channels=CHANNELS,
                                rate=RATE,
                                input=True,
                                frames_per_buffer=CHUNK,
                                input_device_index=self.device_index)
        except Exception as e:
            self.show_error_message("Error initializing audio stream", str(e))
            return

        frames = []

        self.recording = True

        try:
            while self.recording:
                data = stream.read(CHUNK)
                frames.append(data)
        except Exception as e:
            self.show_error_message("Error during recording", str(e))
        finally:
            stream.stop_stream()
            stream.close()
            audio.terminate()

        try:
            with wave.open(self.file_path, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(audio.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(frames))
        except wave.Error as e:
            self.show_error_message("Error saving file", str(e))
        except Exception as e:
            self.show_error_message("Unexpected error", str(e))

        self.finished_recording.emit(self.file_path)

    def stop_recording(self):
        self.recording = False

    def show_error_message(self, title, message):
        QMessageBox.warning(None, title, message)



#Основное окно.
class VoiceAssistantApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.center_on_screen()
        self.microphone_index = None
        self.output_index = None
        self.current_file = None
        self.audio_player = None
        self.recording_thread = None
        self.remembered_audio = False 
        self.rewind_requested = False
        self.initAudioDevices()

    def initAudioDevices(self):
        try:
            default_input_device, default_output_device = sd.default.device
            self.microphone_index = default_input_device
            self.output_index = default_output_device
        except Exception as e:
            self.show_error_message("Ошибка инициализации устройств", str(e))

    def initUI(self):
        self.setGeometry(100, 100, 500, 300)
        self.setWindowTitle('Голосовой исполнитель')
        self.setWindowIcon(QIcon('icon.png'))

        self.audio_label = QLabel('Файл: не найдено | Длительность: 0:00', self)
        self.audio_label.setWordWrap(True)
        self.audio_label.setGeometry(150, 25, 300, 30)

        self.play_button = QPushButton('Воспроиз.', self)
        self.play_button.setGeometry(50, 80, 120, 50)
        self.play_button.clicked.connect(self.play_audio)

        self.pause_button = QPushButton('Пауза', self)
        self.pause_button.setGeometry(200, 80, 120, 50)
        self.pause_button.clicked.connect(self.pause_audio)

        self.rewind_button = QPushButton('Сначала', self)
        self.rewind_button.setGeometry(350, 80, 120, 50)
        self.rewind_button.clicked.connect(self.rewind_audio)

        self.compare_button = QPushButton('Сравнить', self)
        self.compare_button.setGeometry(200, 150, 120, 50)
        self.compare_button.clicked.connect(self.compare_audio)

        self.record_button = QPushButton('Запись', self)
        self.record_button.setGeometry(50, 150, 120, 50)
        self.record_button.clicked.connect(self.record_audio)

        self.record_and_remember_button = QPushButton('Запомнить', self)
        self.record_and_remember_button.setGeometry(350, 150, 120, 50)
        self.record_and_remember_button.clicked.connect(self.record_and_remember_audio)

        self.delete_button = QPushButton('Отчистить', self)
        self.delete_button.setGeometry(200, 220, 120, 50)
        self.delete_button.clicked.connect(self.delete_audio)

        menubar = self.menuBar()

        file_menu = menubar.addMenu('Файл')
        add_file_action = QAction('Добавить файл', self)
        add_file_action.triggered.connect(self.add_file)
        file_menu.addAction(add_file_action)

        save_file_action = QAction('Сохранить файл', self)
        save_file_action.triggered.connect(self.save_file)
        file_menu.addAction(save_file_action)

        settings_menu = menubar.addMenu('Параметры')
        settings_action = QAction('Параметры', self)
        settings_action.triggered.connect(self.show_settings_dialog)
        settings_menu.addAction(settings_action)

        help_menu = menubar.addMenu('Помощь')
        help_action = QAction('Помощь', self)
        # help_action.triggered.connect()
        help_menu.addAction(help_action)

    def save_file(self):
        if self.current_file:
            if self.audio_player:
                self.audio_player.stop()
                self.audio_player.wait()
                self.audio_player = None

            options = QFileDialog.Options()
            file_name, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", "", "WAV Audio (*.wav);;MP3 Audio (*.mp3);;All Files (*)", options=options)
            if file_name:
                try:
                    if file_name.endswith('.wav'):
                        shutil.copy2(self.current_file, file_name)
                    elif file_name.endswith('.mp3'):
                        audio = AudioSegment.from_wav(self.current_file)
                        audio.export(file_name, format="mp3")
                    else:
                        shutil.copy2(self.current_file, file_name)

                    os.remove(self.current_file)
                    self.current_file = None
                    self.audio_label.setText('Файл: не найдено | Длительность: 0:00')
                except Exception as e:
                    self.show_error_message("Ошибка при сохранении файла", str(e))

    def show_settings_dialog(self):
        settings_dialog = SettingsDialog(self, self.microphone_index, self.output_index)
        settings_dialog.move(self.x() + 50, self.y() + 50)
        if settings_dialog.exec_():
            self.microphone_index = settings_dialog.microphone_combo.currentData()
            self.output_index = settings_dialog.output_combo.currentData()

    def center_on_screen(self):
        screen_geometry = QDesktopWidget().screenGeometry()
        window_geometry = self.frameGeometry()
        window_geometry.moveCenter(screen_geometry.center())
        self.move(window_geometry.topLeft())

    def play_audio(self):
        if self.current_file:
            if not self.audio_player:
                self.audio_player = AudioPlayer(self.current_file, device_index=self.output_index)
                self.audio_player.start()
            else:
                if self.rewind_requested:
                    self.audio_player.terminate()
                    self.audio_player.wait()
                    self.audio_player = AudioPlayer(self.current_file, device_index=self.output_index)
                    self.audio_player.start()
                    self.rewind_requested = False
                else:
                    self.audio_player.resume()

    def rewind_audio(self):
        if self.audio_player:
            self.audio_player.stop()
            self.audio_player = None

    def pause_audio(self):
        if self.audio_player:
            self.audio_player.pause()

    def delete_audio(self):
        if self.audio_player:
            self.audio_player.stop()
            self.audio_player.wait()
            self.audio_player = None

        if self.recording_thread and self.recording_thread.isRunning():
            self.recording_thread.stop_recording()
            self.recording_thread.wait()
            self.recording_thread = None

        if self.current_file:
            if not self.remembered_audio:
                try:
                    if os.path.exists(self.current_file):
                        os.remove(self.current_file)
                except Exception as e:
                    self.show_error_message("Ошибка при удалении файла", str(e))
            self.current_file = None
            self.audio_label.setText('Файл: не найдено | Длительность: 0:00')
            self.remembered_audio = False

    def compare_audio(self):
        if not self.current_file:
            QMessageBox.warning(self, "Ошибка", "Плеер пустой. Добавьте аудиофайл для сравнения.")
            return

        selected_file, _ = QFileDialog.getOpenFileName(self, "Выбрать файл для сравнения", "remember_sounds", "WAV Audio (*.wav)")
        if selected_file:
            recognizer = sr.Recognizer()

            try:
                with sr.AudioFile(self.current_file) as source:
                    audio_data = recognizer.record(source)
                    user_audio_text = recognizer.recognize_google(audio_data, language="ru-RU")

                with sr.AudioFile(selected_file) as source:
                    audio_data = recognizer.record(source)
                    selected_audio_text = recognizer.recognize_google(audio_data, language="ru-RU")

                result = "Фразы совпадают!" if user_audio_text.lower() == selected_audio_text.lower() else "Фразы не совпадают!"
                QMessageBox.information(self, "Результат сравнения", result)
            except sr.RequestError as e:
                self.show_error_message("Ошибка при запросе к сервису распознавания речи", str(e))
            except sr.UnknownValueError:
                self.show_error_message("Ошибка распознавания", "Не удалось распознать аудиофайл.")
            except Exception as e:
                self.show_error_message("Неизвестная ошибка", str(e))

    def record_audio(self):
        self.remembered_audio = False
        if self.recording_thread and self.recording_thread.isRunning():
            self.recording_thread.stop_recording()
            self.recording_thread.wait()
            self.recording_thread = None
            self.record_button.setText('Запись')
            return

        temp_dir = tempfile.gettempdir()
        temp_wav_file = os.path.join(temp_dir, "Ваша запись.wav")

        if temp_wav_file:
            if self.audio_player:
                self.audio_player.terminate()
                self.audio_player.wait()
                self.audio_player = None
            self.audio_label.setText('Файл: Идет запись... | Длительность: 0:00')
            self.record_button.setText('Остановить')
            self.recording_thread = AudioRecorder(temp_wav_file, device_index=self.microphone_index)

            self.recording_thread.finished_recording.connect(self.update_current_file)
            self.recording_thread.start()

    def record_and_remember_audio(self):
        if self.recording_thread and self.recording_thread.isRunning():
            self.recording_thread.stop_recording()
            self.recording_thread.wait()
            self.recording_thread = None
            self.record_and_remember_button.setText('Запомнить')
            return

        folder_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'remember_sounds')
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        file_name = f"remember_sounds/saves_{len(os.listdir(folder_path)) + 1}.wav"

        if file_name:
            if self.audio_player:
                self.audio_player.terminate()
                self.audio_player.wait()
                self.audio_player = None
            self.audio_label.setText('Файл: Идет запись... | Длительность: 0:00')
            self.record_and_remember_button.setText('Остановить')
            self.recording_thread = AudioRecorder(file_name, device_index=self.microphone_index)

            self.recording_thread.finished_recording.connect(self.update_current_file)
            self.recording_thread.start()
            self.remembered_audio = True

    def update_current_file(self, file_path):
        self.current_file = file_path
        try:
            audio = AudioSegment.from_file(file_path)
            duration = len(audio) / 1000
            self.audio_label.setText(f'Файл: Ваша запись.wav | Длительность: {duration:.2f} сек.')
        except Exception as e:
            self.show_error_message("Ошибка при обновлении текущего файла", str(e))

    def add_file(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Добавить файл", "", "Audio Files (*.mp3 *.wav)", options=options)
        if file_name:
            label_name = os.path.basename(file_name)
            try:
                if file_name.lower().endswith('.mp3'):
                    temp_dir = tempfile.gettempdir()
                    self.temp_wav_file = os.path.join(temp_dir, 'temp_audio.wav')
                    AudioSegment.from_mp3(file_name).export(self.temp_wav_file, format='wav')
                    self.current_file = self.temp_wav_file
                else:
                    self.current_file = file_name
                audio = AudioSegment.from_file(self.current_file)
                duration = len(audio) / 1000
                self.audio_label.setText(f'Файл: {label_name} | Длительность: {duration:.2f} сек.')
            except Exception as e:
                self.show_error_message("Ошибка при добавлении файла", str(e))

    def show_error_message(self, title, message):
        QMessageBox.warning(self, title, message)



#Окно настроек.
class SettingsDialog(QDialog):
    def __init__(self, parent=None, microphone_index=None, output_index=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")

        layout = QVBoxLayout()

        microphone_layout = QHBoxLayout()
        self.microphone_label = QLabel("Микрофон:")
        self.microphone_combo = QComboBox()
        self.populate_audio_devices(self.microphone_combo, input=True)
        microphone_layout.addWidget(self.microphone_label)
        microphone_layout.addWidget(self.microphone_combo)
        layout.addLayout(microphone_layout)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        output_layout = QHBoxLayout()
        self.output_label = QLabel("Наушники:")
        self.output_combo = QComboBox()
        self.populate_audio_devices(self.output_combo, input=False)
        output_layout.addWidget(self.output_label)
        output_layout.addWidget(self.output_combo)
        layout.addLayout(output_layout)

        buttons_layout = QHBoxLayout()
        self.cancel_button = QPushButton("Отменить")
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button = QPushButton("Применить")
        self.apply_button.clicked.connect(self.accept)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.apply_button)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

        if microphone_index is not None:
            self.microphone_combo.setCurrentIndex(self.microphone_combo.findData(microphone_index))
        if output_index is not None:
            self.output_combo.setCurrentIndex(self.output_combo.findData(output_index))

        self.recording = None

    def populate_audio_devices(self, combo_box, input=True):
        try:
            devices = sd.query_devices()
            for device in devices:
                device_name = device['name']
                device_index = device['index']
                if input and device['max_input_channels'] > 0:
                    combo_box.addItem(device_name, device_index)
                elif not input and device['max_output_channels'] > 0:
                    combo_box.addItem(device_name, device_index)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить устройства: {str(e)}")



#Для запуска
def main():
    app = QApplication(sys.argv)
    window = VoiceAssistantApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
